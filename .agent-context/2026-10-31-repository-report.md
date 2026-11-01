# Rapport d’analyse du dépôt omarchy-mcp

Date : 31 octobre 2026. Périmètre : code Python, tests, documentation et installateur du dépôt. Cette analyse ne modifie pas le code applicatif et ne constitue pas une validation sur un bureau réel.

## Synthèse

Le projet est un serveur MCP local qui permet à un client d’interroger et, partiellement, de manipuler un bureau Hyprland sous Wayland. Il expose 27 outils ; une partie significative des actions est délibérément désactivée. Le README indique explicitement de ne pas déployer ce brouillon. Les capacités restantes manipulent des données et applications accessibles à la session utilisateur : ce serveur n’est pas un bac à sable.

La charge envisagée ici est celle d’un utilisateur contrôlant sa propre session graphique, pas celle d’un service multiclient exposé sur Internet. La sécurité dépend de la confiance accordée au client MCP et aux contenus qu’il traite.

## 1. Stack et organisation

| Élément | Rôle |
|---|---|
| Python ≥ 3.10 | Langage et runtime déclarés ; projet version 0.1.0. |
| `mcp[cli]<2`, FastMCP | Enregistrement des outils, validation du protocole MCP et transport standard input/output (`stdio`). |
| Pillow | Décodage, redimensionnement et compression JPEG des captures. |
| pytesseract et Tesseract | Reconnaissance optique des caractères (OCR) sur les captures. |
| Hyprland et `hyprctl` | Compositeur Wayland et accès à son état en JSON. |
| `grim`, `wtype`, `ydotool`, `wl-copy`, `wl-paste` | Capture, saisie de texte, événements souris et presse-papiers. |
| Hatchling et pipx | Construction et installation ; `install.sh` peut enregistrer le serveur dans Claude Code. |
| `unittest` et mocks | Tests de logique, d’erreurs et d’intégration MCP simulée. |

Les versions de Pillow et pytesseract ne sont pas bornées dans `pyproject.toml`, et la dépendance MCP n’a qu’une borne supérieure. Le README rapporte une validation antérieure limitée à Python 3.11.6 et MCP 1.30.0 ; ces versions ne garantissent pas la compatibilité de toute la plage déclarée. Références : `pyproject.toml:1-19`, `README.md:20-54`.

| Fichier | Responsabilité |
|---|---|
| `hyprland_mcp/server.py` | Instance FastMCP, 27 outils, orchestration et messages d’erreur. |
| `hyprland_mcp/hyprctl.py` | Requêtes Hyprland JSON ; refus des actions dispatch et batch. |
| `hyprland_mcp/screenshot.py` | Géométrie, capture `grim`, vérification PNG, redimensionnement et mapping. |
| `hyprland_mcp/ocr.py` | Prétraitement d’image, OCR Tesseract, recherche de texte et boîtes. |
| `hyprland_mcp/input.py` | Saisie clavier et événements souris ; appels dispatch pour le positionnement. |
| `hyprland_mcp/clipboard.py` | Lecture et écriture du presse-papiers texte. |
| `hyprland_mcp/errors.py` | Exceptions et vérification de présence des exécutables. |
| `install.sh` | Installation pipx et enregistrement facultatif, sans installer les outils système. |
| `tests/` | Tests unitaires et simulés ; test du protocole stdio ; contrôles statiques de l’installateur. |

## 2. Fonctionnement de bout en bout

1. L’installation déclare la commande `hyprland-mcp`, qui appelle `server.main`. Celui-ci démarre `SafeFastMCP` avec le transport `stdio` ; le client lance donc le serveur comme sous-processus et échange avec lui sur ses flux standard (`pyproject.toml:18-19`, `server.py:674-682`).
2. Les fonctions décorées avec `@mcp.tool()` forment l’interface de 27 outils. Les annotations et le SDK participent à la validation ; le code ajoute des contrôles sur certains arguments. La couche `SafeFastMCP` remplace les erreurs ordinaires par un message générique et conserve deux messages d’indisponibilité contrôlés (`server.py:18-44`).
3. Les opérations de lecture de l’état appellent `hyprctl -j` dans un sous-processus, décodent le JSON et le formatent. Aucun shell n’est utilisé pour construire ces commandes (`hyprctl.py:9-30`).
4. Les actions permises délèguent à des exécutables du système. Les entrées du client sont transmises par des arguments séparés ou, pour `wl-copy`, par l’entrée standard. Ces opérations héritent des privilèges et de l’environnement de la session utilisateur (`input.py:39-76,121-136`, `clipboard.py:8-35`).

### Outils disponibles et désactivés

| Catégorie | État actuel dans le code |
|---|---|
| Moniteurs, espaces, fenêtres, curseur | Consultation implémentée via `hyprctl`. |
| Capture et OCR | Capture d’un écran, d’une fenêtre ou d’une région ; recherche de texte et extraction OCR implémentées. |
| Souris | Clic et défilement à la position courante implémentés ; positionnement et glisser désactivés. |
| Clavier | Saisie de texte via `wtype` implémentée ; raccourcis désactivés. |
| Presse-papiers | Lecture et écriture du texte implémentées. |
| Actions fenêtres/espaces | Désactivées par le refus systématique de `hyprctl.dispatch`. |
| `click_text`, `type_into` | Désactivés avant capture ou OCR. |
| Lancement d’applications | Désactivé avant lecture d’une configuration ou démarrage d’un processus. |

« Implémenté » signifie qu’un chemin de code existe, pas qu’il a été validé sur une session réelle. Le blocage de dispatch est un choix de sécurité déjà documenté, pas une nouvelle faille découverte par cet audit (`hyprctl.py:33-41`, `server.py:274-281,579-630`).

### Captures et coordonnées

Le serveur lit la géométrie des moniteurs, transforme les résolutions physiques en rectangles logiques et choisit une fenêtre, une région, un moniteur ou le rectangle englobant tous les moniteurs. Il refuse les géométries ambiguës, écrans qui se chevauchent et régions comportant des zones non couvertes. Il lance ensuite `grim` avec une échelle 1, contrôle le PNG et compare les dispositions avant et après la capture. Pour une fenêtre explicite, il compare également son identité et sa géométrie (`screenshot.py:15-172`).

Pillow produit ensuite un JPEG et le serveur indique comment convertir les pixels de l’image vers les coordonnées logiques absolues (`screenshot.py:175-227`). Un contrôle avant/après ne rend pas l’opération atomique : une fenêtre peut en masquer une autre ou changer temporairement avant de revenir à son état initial. Le README précise que la précision de cette correspondance n’est pas validée sur un véritable bureau multimoniteur.

### OCR

Par défaut, l’OCR capture le rectangle de la fenêtre active ; si aucune fenêtre n’est active, il capture tout le bureau. Une fenêtre explicite, un moniteur ou une région peuvent restreindre le périmètre. Le texte est extrait après passage en niveaux de gris, inversion si l’image est globalement sombre et accentuation. `find_text_on_screen` fournit des coordonnées estimées ; `screenshot_with_ocr` fournit l’image et le texte sans coordonnées des mots (`server.py:485-576,633-671`, `ocr.py:15-129`).

Une capture de fenêtre est une capture de rectangle visible, non une extraction isolée de la fenêtre ; elle peut donc contenir des informations d’une autre fenêtre superposée. Quand la recherche OCR ne trouve pas la cible, elle renvoie un aperçu du texte reconnu, ce qui doit être pris en compte par le client.

### Installation et exploitation

`install.sh` préfère le checkout local lorsqu’il est lancé depuis celui-ci, sinon l’URL Git configurée ; il vérifie la présence de pipx, signale les exécutables optionnels manquants et installe le projet. Si Claude Code est présent, il conserve une éventuelle entrée MCP existante au lieu de la remplacer. L’installateur n’installe pas les paquets système, ne règle pas le démon `ydotool` et ne configure pas les permissions Wayland (`install.sh:4-73`, `README.md:43-89`).

## 3. Bugs, sécurité et autres risques

Deux sous-agents ont mené séparément une recherche de bugs et une revue de sécurité, après la cartographie. Les sévérités ci-dessous concernent une utilisation locale par un client MCP autorisé ; elles ne supposent pas que le serveur soit accessible sur Internet. Aucun correctif n’a été appliqué.

### 3.1 Capture d’une fenêtre différente de celle demandée — élevée

**Code :** `hyprland_mcp/screenshot.py:81-104,121-123,164-171`.

Le sélecteur prend la première fenêtre correspondant à une classe ou à un titre, sans vérifier si sa workspace est visible. Une fenêtre Firefox masquée sur une autre workspace peut être sélectionnée avant la fenêtre Firefox visible ; `grim` capture alors son rectangle à l’écran, qui peut montrer une application entièrement différente. Les contrôles avant/après ne détectent pas ce cas s’il reste stable. Une simulation a confirmé la sélection de la fenêtre masquée. Le comportement effectif et le contenu dépendent du compositeur et n’ont pas été observés sur un bureau réel.

**Conséquence :** réponse incorrecte et divulgation possible d’un contenu autre que celui attendu. **Correction proposée :** refuser les cibles non visibles et gérer explicitement les sélecteurs ambigus ; vérifier sur un vrai bureau les règles de visibilité, y compris les workspaces spéciales et plusieurs moniteurs. Le simple contrôle de visibilité ne supprime pas les occultations déjà documentées.

### 3.2 Sélecteur de titre vide accepté — moyenne

**Code :** `hyprland_mcp/screenshot.py:85-90,114-122`.

La valeur `window="title:"` n’est pas une chaîne vide, mais la recherche utilise ensuite une sous-chaîne vide, qui correspond à n’importe quel titre. Une simulation a confirmé que le premier client est sélectionné. Il ne s’agit pas d’un contournement démontré d’une autorisation par fenêtre : aucun tel contrôle n’existe et le client dispose d’autres modes de capture.

**Conséquence :** capture involontaire et potentiellement sensible si le client construit un sélecteur vide. **Correction proposée :** rejeter les valeurs vides ou composées d’espaces après le préfixe avant de lancer une capture.

### 3.3 Recherche OCR multi-mots et coordonnées erronées — moyenne

**Code :** `hyprland_mcp/ocr.py:59-75,105-125`, `hyprland_mcp/server.py:559-575`.

Les identifiants de ligne et de bloc OCR sont perdus, les mots à faible confiance sont filtrés, puis deux boîtes sont considérées comme une phrase si leurs ordonnées sont proches. Une démonstration avec `Save` à x=10 et `changes` à x=1500 a renvoyé une boîte unique de largeur 1530, malgré la distance. Si les mots sont fournis dans l’ordre inverse spatial, la boîte qui commence au x du premier mot peut aussi exclure le second.

**Conséquence :** faux positifs et coordonnées de texte trompeuses. `click_text` étant désactivé, aucun clic automatique n’a été démontré. **Correction proposée :** conserver l’identité et l’ordre des mots d’origine, tenir compte des lignes et espacements, puis utiliser les coordonnées minimales et maximales pour fusionner les boîtes. Ajouter des tests de colonnes, d’ordre inverse et de mots intermédiaires filtrés.

### 3.4 OCR bloquant et forte consommation mémoire — moyenne

**Code :** `hyprland_mcp/server.py:559-564,668-669`, `hyprland_mcp/ocr.py:21-34,39-57`, `hyprland_mcp/screenshot.py:23-26`.

Les traitements OCR synchrones sont appelés directement depuis des outils asynchrones. Une simulation de travail synchrone a empêché une autre coroutine de reprendre pendant l’OCR ; en cas de recherche infructueuse, une deuxième reconnaissance est demandée. Le prétraitement construit également une liste de tous les pixels. Avec la limite actuelle de 100 millions de pixels, les seules références de cette liste peuvent occuper environ 800 Mo sur une architecture 64 bits, hors images et processus OCR. L’atteinte de cette taille dépend de la disposition réelle des moniteurs.

**Conséquence :** autres requêtes retardées, délai d’annulation et risque d’épuisement mémoire. **Correction proposée :** calculer la luminosité avec un histogramme ou un échantillon, limiter la taille traitée, déplacer le travail bloquant hors de la boucle et donner au processus Tesseract un délai réellement applicable avec nettoyage. Un délai autour d’un simple thread ne suffit pas à arrêter son travail.

### 3.5 Texte saisi visible dans les arguments de processus — moyenne

**Code :** `hyprland_mcp/input.py:121-134`, `hyprland_mcp/server.py:392-402`.

Le texte fourni à `type_text` est passé intégralement dans les arguments de `wtype`. Une simulation confirme la présence d’un marqueur public dans les arguments. Un autre processus ou outil de surveillance autorisé à lire la ligne de commande peut donc voir le texte pendant la vie de `wtype` ; la portée exacte dépend des identités et de la configuration de la machine. Aucune élévation de privilèges n’a été démontrée.

**Conséquence :** exposition possible de secrets saisis. **Correction proposée :** vérifier si la version de `wtype` prise en charge peut recevoir le texte sur son entrée standard, sinon choisir une interface qui n’expose pas les données dans `argv` ; à défaut, documenter explicitement l’interdiction de saisir des secrets ainsi.

### 3.6 Presse-papiers lu sans limite ni délai — moyenne, sous conditions

**Code :** `hyprland_mcp/clipboard.py:8-22`.

`wl-paste` est attendu avec `communicate()`, qui collecte sa sortie sans taille maximale ni délai explicite. Si le fournisseur du presse-papiers tarde indéfiniment ou fournit beaucoup de données, la requête peut rester bloquée ou consommer une mémoire excessive. Une simulation a confirmé l’absence de terminaison explicite de l’enfant lors d’une annulation ; le comportement d’un fournisseur Wayland réel et l’épuisement mémoire effectif n’ont pas été testés.

**Correction proposée :** lecture bornée par blocs, délai explicite et arrêt puis collecte du sous-processus lors d’un dépassement ou d’une annulation. Examiner les mêmes limites pour les autres sous-processus.

### 3.7 Correspondance des coordonnées absente de `screenshot_with_ocr` — faible à moyenne

**Code :** `hyprland_mcp/server.py:661-671`, `README.md:11`, `hyprland_mcp/screenshot.py:200-227`.

Contrairement à l’affirmation générale du README selon laquelle chaque capture inclut une correspondance, `screenshot_with_ocr` renvoie l’image et le texte mais pas l’origine ni les facteurs de redimensionnement ; il récupère pourtant l’origine. Le client ne peut donc pas convertir de façon fiable une position sur cette image en coordonnées absolues. Les clics positionnés sont actuellement désactivés, ce qui limite l’impact immédiat.

**Correction proposée :** inclure le même guide que pour `screenshot`, basé sur les dimensions réelles après arrondi, ou corriger explicitement le contrat documenté si l’absence de mapping est voulue.

### 3.8 Captures ciblées refusées à cause d’autres moniteurs — faible à moyenne

**Code :** `hyprland_mcp/screenshot.py:31-67,118-129`.

La validation porte sur tous les moniteurs avant la sélection d’un écran particulier. Ainsi, un chevauchement ou une géométrie fractionnaire ambiguë sur deux sorties peut aussi empêcher la capture d’un troisième écran indépendant et valide. Ce refus global est une mesure conservatrice documentée, et non un contournement de sécurité.

**Conséquence :** perte de disponibilité inutile dans certaines configurations. **Correction proposée :** n’assouplir cette validation qu’après avoir établi quelles sorties peuvent affecter le rectangle ciblé et disposer de tests réels de géométrie ; continuer à refuser tout cas ambigu pour ce rectangle.

### 3.9 Risque transversal : données du bureau et instructions injectées

Les titres de fenêtres, le presse-papiers et le texte OCR proviennent de sources non fiables et sont transmis au client (`server.py:119-139,252-256,559-575`). Une page ou application peut placer dans un titre des instructions destinées au modèle. Le code confirme le transport de ces données, mais **aucun comportement d’un client ou modèle particulier n’a été démontré**.

La défense principale relève du client : conserver la provenance, traiter ces champs comme des données et demander une approbation adaptée avant les actions sensibles. Une sortie structurée aide à en délimiter les champs mais ne neutralise pas à elle seule une injection de prompt.

### 3.10 Couverture sécurité et ordre proposé

La revue statique a examiné les frontières d’arguments des sous-processus, les captures, les entrées, le presse-papiers, la gestion d’erreurs et l’installateur. Les commandes Python examinées utilisent des arguments séparés plutôt qu’un shell ; le refus de dispatch et de lancement est effectif dans le code. Cela ne démontre pas l’absence de toutes les injections ou erreurs dans les dépendances.

Pour le référentiel OWASP 2021 : A01 et A04 sont concernés par les frontières de confiance et capacités du client ; A03 par les arguments et données non fiables ; A05 et A08 par la configuration et l’approvisionnement en dépendances, dont l’intégrité n’a pas été vérifiée ; A06 n’a pas été audité contre une base de CVE ; A09 est partiellement examiné pour la sanitisation des erreurs. A02, A07 et A10 ne sont pas directement applicables au code applicatif examiné, qui ne définit ni mécanisme cryptographique, ni authentification HTTP, ni récupération d’URL serveur ; cela ne couvre pas les dépendances ou un éventuel client externe.

**Priorité recommandée :** d’abord empêcher les captures de mauvaise cible et les sélecteurs vides ; ensuite corriger la recherche OCR et son budget de ressources ; puis protéger la saisie sensible et borner les sous-processus. Ne pas réactiver dispatch ni le lancement sans une conception de sécurité distincte et une validation sur un bureau réel.

## 4. Vérifications et limites

- Revue statique du dépôt et analyses séparées par sous-agents.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p <fichier> -q`, pour `test_clipboard.py`, `test_hyprctl.py`, `test_input.py` et `test_installer.py` : 16 tests réussis, dont 6 contrôles statiques de l’installateur ; le script lui-même n’a pas été exécuté.
- `bash -n install.sh` : syntaxe valide. Analyse syntaxique Python avec `ast.parse` : 15 fichiers valides.
- Démonstrations locales sans dépendances externes : sélection d’une fenêtre masquée et de `title:`, arguments simulés de `wtype`, fausse expression OCR. Les sous-agents ont aussi simulé le blocage OCR et l’attente du presse-papiers ; aucun bureau ni processus système réel n’a été manipulé.
- L’interpréteur courant est Python 3.11.6 ; les modules MCP, Pillow et pytesseract ne sont pas installés dans cet environnement. La suite complète ne peut pas être exécutée sans installation supplémentaire.
- Aucun Hyprland, outil de capture, session Wayland réelle ou démon `ydotool` n’a été testé ; aucun scan actif externe n’a été lancé. Aucun audit automatisé des CVE des dépendances n’a été réalisé.
