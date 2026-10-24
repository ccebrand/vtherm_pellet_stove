# Revue de l'issue #7 : panne apres reconfiguration du poele

## Reference et constat signale

- Issue : [jmcollin78/vtherm_pellet_stove#7](https://github.com/jmcollin78/vtherm_pellet_stove/issues/7), ouverte par jmcollin78, sans commentaire, etiquette, relation ou PR associee visibles lors de la consultation.
- Fait rapporte, non reproduit localement : apres changement d'un parametre (par exemple un delai), l'entite de diagnostic ne presente plus que des valeurs vides et l'integration ne fonctionne plus.
- Comportement attendu par l'auteur : appliquer les nouveaux seuils et delais, conserver le cycle en cours, et recalculer si necessaire `next_action_allowed_at`. Si un changement de parametres doit provoquer une action marche/arret, celle-ci est attendue au redemarrage de l'integration.

## Sources et elements verifies

- Description et metadonnees publiques de l'[issue #7](https://github.com/jmcollin78/vtherm_pellet_stove/issues/7) ; aucune trace d'execution, version de HA/VTherm ni sequence reproductible precise n'y figure.
- [`config_flow.py`](../../custom_components/vtherm_pellet_stove/config_flow.py) : la reconfiguration modifie `entry.data`, vide `entry.options` et appelle `async_update_reload_and_abort` ; le flux d'options met les valeurs dans `entry.options`.
- [`__init__.py`](../../custom_components/vtherm_pellet_stove/__init__.py) : le listener d'options recharge l'entree du plugin ; son setup recharge les entrees VTherm utilisant `pellet_regulation` quand HA est en marche. Le dechargement de l'entree globale decharge la plateforme sensor et supprime son callback ; si c'est la derniere entree, la factory est egalement desenregistree et des VTherms sont recharges.
- [`handler.py`](../../custom_components/vtherm_pellet_stove/handler.py) : `init_algorithm` cree un controleur avec les options courantes ; `async_added_to_hass` restaure l'etat depuis un `Store` et reprend l'objet capteur garde dans `hass.data` s'il existe ; `remove` programme une sauvegarde asynchrone. `async_startup` et `control_heating` peuvent recalculer et commander des transitions.
- [`sensor.py`](../../custom_components/vtherm_pellet_stove/sensor.py), [`controller.py`](../../custom_components/vtherm_pellet_stove/pellet/controller.py) et [`state.py`](../../custom_components/vtherm_pellet_stove/pellet/state.py) : le capteur ne recoit des valeurs que lors d'une mise a jour par le handler ; `next_action_allowed_at` est derive des horodatages conserves et des nouvelles durees ; le `Store` persiste l'etat du poele, pas l'etat complet du scheduler ni la derniere decision.
- [`test_handler.py`](../../tests/test_handler.py) et [`test_services.py`](../../tests/test_services.py) : tests de lecture des options, restauration, reutilisation du capteur entre handlers et cycle de vie des services ; pas de scenario integre de reconfiguration avec dechargement de la plateforme, persistance en vol et controle du cycle. La [documentation technique FR](../fr/technical_doc.md) prevoit actuellement le rechargement automatique des VTherms a la modification des options.

## Pertinence et recommandation

**Retenir le probleme pour investigation et correction**, sous reserve de confirmer le mecanisme par un test de reconfiguration representatif. La panne rapportee touche le pilotage d'un chauffage et la visibilite de son etat ; elle est donc prioritaire. Le chemin de rechargement existant est en tension avec la conservation du cycle demandee, mais aucun test de bout en bout ni journal ne prouve encore que ce seul chemin explique la panne.

Hypothese principale falsifiable : lors d'un rechargement de l'entree globale, la plateforme sensor est dechargee alors que `hass.data` conserve l'ancien objet capteur ; la recreation du handler le reprend sans l'enregistrer a nouveau. Verifier en dechargeant/rechargeant la plateforme dans un test HA et en observant l'enregistrement et les attributs du capteur. Hypothese concurrente : le dechargement de la derniere entree desenregistre temporairement la factory et recharge les VTherms, ou la sauvegarde differee du handler precedent entre en conflit avec la restauration du nouveau. Verifier l'ordre effectif des appels et du `Store` avant de choisir la correction.

## Perimetre propose

- Couvrir reconfiguration et flux d'options, pour l'entree globale et une entree par thermostat, en respectant la priorite des valeurs de configuration.
- Appliquer les nouveaux parametres sans perdre l'etat du poele ni les horodatages du cycle courant ; actualiser le diagnostic, notamment `next_action_allowed_at`, et eviter une commande marche/arret indue pendant la reconfiguration.
- Clarifier et tester le cycle de vie de la factory, des handlers, du capteur de diagnostic et du `Store` lors des rechargements ; synchroniser la documentation FR/EN du comportement retenu.
- Hors perimetre : changement du protocole du poele, modification des integrations VTherm ou Duepi, nouvelle interface de configuration, remise a zero volontaire de l'historique.

## Impacts et risques

| Risque / impact                                                              | Gravite | Probabilite            | Motif et mesure envisagee                                                                                                                  |
| ---------------------------------------------------------------------------- | ------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Transition ON/OFF non desiree pendant la reconfiguration                     | Elevee  | Indeterminee           | Le controle au demarrage peut declencher une transition ; tester poele allume, eteint et delais modifies avant toute mise en service.      |
| Diagnostic vide ou obsolete apres rechargement global                        | Moyenne | Plausible, non mesuree | Cache du capteur conserve alors que la plateforme est dechargee ; tester le cycle complet de la plateforme.                                |
| Etat perdu ou restaure depuis une sauvegarde asynchrone perimee              | Elevee  | Indeterminee           | `remove` programme l'ecriture sans synchronisation visible avec le rechargement du nouveau handler ; verifier l'ordre et les cas d'erreur. |
| VTherm temporairement prive de factory au dechargement de la derniere entree | Elevee  | Plausible, non mesuree | Sequence de dechargement/rechargement a instrumenter et tester avec une seule entree globale.                                              |
| Divergence entre nouvelles options et cycle scheduler deja actif             | Moyenne | Indeterminee           | Definir ce qui doit rester fige jusqu'a la fin du cycle et les regles d'application des nouveaux delais.                                   |

Compatibilite : conserver les entrees existantes, les cles de stockage, les identifiants des capteurs et les configurations par thermostat. Securite/confidentialite : aucun nouveau traitement de donnees personnelles prevu ; le risque majeur est la surete operationnelle du chauffage, en particulier une commande intempestive. Exploitation : diagnostic et journaux doivent permettre de differencier un rechargement normal d'une perte d'etat ; eviter de journaliser des informations sensibles. Migration de donnees : non justifiee a ce stade, a reevaluer selon la correction retenue.

## Alternatives examinees

1. Mise a jour des parametres du handler/controleur en place, sans dechargement VTherm : conserve plus facilement le cycle et evite la fenetre d'indisponibilite ; demande un contrat explicite de mise a jour et de synchronisation avec le controle en cours.
2. Conserver le rechargement, mais assurer transfert atomique de l'etat, du capteur et de la factory : reutilise le flux actuel ; risque plus eleve de courses et de perturbation du scheduler, a valider en integration.
3. Contournement provisoire par redemarrage HA apres modification : peut retablir l'affichage si l'etat persiste est sain, sans garantie et avec interruption de service ; ne satisfait pas l'exigence de preservation du cycle. A ne pas presenter comme correctif confirme.

## Hypotheses et decisions necessaires

- Precision ulterieure de l'utilisateur (2026-10-23) : l'auteur entend par "redemarrage de l'integration" le rechargement de l'integration avec les nouveaux parametres. Une action rendue necessaire par ces parametres est donc attendue a ce rechargement, et non a un redemarrage obligatoire de HA. Le moment exact des commandes de securite et la prevention des commandes parasites restent a specifier et tester.
- Precisons ulterieures de l'utilisateur (2026-10-23) : une entree specifique constitue une configuration complete et ne doit jamais melanger ses parametres avec ceux de l'entree centrale ; apres rechargement de Pellet Stove, la regulation et le diagnostic restent identiques vus de l'utilisateur sauf les effets justifies par les nouveaux parametres. Le VTherm ne doit etre ni reconfigure ni recharge : une transition de chauffe justifiee peut etre pilotee par Pellet Stove sans modifier sa configuration. Si le nouveau seuil de securite est deja depasse, arreter le poele au rechargement meme pendant le minimum de chauffe. Si la conservation de l'etat echoue, appliquer tout de meme les nouveaux parametres et journaliser l'echec ; ne pas annoncer une restauration reussie.
- Precisons ulterieures de l'utilisateur (2026-10-24) : si l'etat physique du poele devient incertain apres un echec de reprise, appliquer les nouveaux parametres et journaliser l'erreur, mais ne pas envoyer d'ordre automatique d'allumage ; un arret de securite reste autorise. Si une commande est deja en cours lors du rechargement, la laisser se terminer puis reprendre le cycle et reevaluer les nouveaux parametres, sauf arret de securite prioritaire.
- Parcours observe selon l'utilisateur : roue dentee "Configurer" ouvrant Options sur une entree specifique a un VTherm. Reconfigurer et l'entree globale ne sont pas confirmes comme reproductions ; l'utilisateur estime pouvoir reproduire le defaut localement mais aucun test ni journal n'a encore ete consulte. L'hypothese initiale du capteur decharge avec la plateforme globale ne suffit donc pas a expliquer a elle seule ce parcours local ; sa causalite reste a verifier.
- A verifier : versions de HA, VTherm et du plugin, parametre modifie, traces d'une reproduction et etat reel du poele et du diagnostic avant/apres. Tester les autres parcours sans leur attribuer une panne observee.
- A verifier : existence de doublons non lies ; la page de l'issue ne signale aucune relation ou PR, ce qui ne prouve pas l'absence de travail parallele.

## Suite proposee et criteres de passage au developpement

1. Faire valider ce rapport et les questions de comportement par l'utilisateur.
2. Rediger et faire converger specification fonctionnelle et conception technique ; definir les invariants du cycle, le moment d'application des commandes et le traitement de la plateforme sensor.
3. Faire valider ces resultats avant tout developpement. La precision recue sur le rechargement doit etre integree aux specifications et a la conception ; les autres arbitrages bloquants doivent etre leves avant ce jalon.
4. Pour la mise en oeuvre autorisee : exiger des tests de reconfiguration globale/par thermostat, Options/Reconfigurer, etat chauffe/arret, preservation des horodatages et du cycle, diagnostic enregistre et actualise, absence de commandes inattendues, restauration et ordre de sauvegarde. Mettre a jour la documentation d'utilisation et verifier les tests pertinents.

**Statut : rapport valide le 2026-10-23 ; specifications et conception validees et developpement autorise par l'utilisateur le 2026-10-24 dans ce perimetre, sous reserve des verifications de faisabilite technique.**

## Resultat de verification technique (2026-10-24)

Le parcours Options local a ete simule avec le cycle HA `unload -> setup`, une entree globale deja chargee, un handler reel et son capteur de diagnostic. Apres le changement de `min_on_duration_min` de 10 a 42, aucun reload VTherm n'a lieu, mais le handler et le diagnostic gardent la valeur 10 : l'application des options sur le runtime est donc reproduite comme defaillante. Le capteur conserve un etat et des attributs non vides dans ce test ; le symptome rapporte de diagnostic vide et la panne effective de pilotage ne sont pas reproduits. Sans entree globale, le dernier unload appelle encore `_reload_pellet_vtherms`, en contradiction avec l'exigence de ne jamais recharger VTherm.

Le contrat `vtherm_api` 0.7.0 installe expose le cycle de vie du handler, pas d'operation publique de mise a jour, de resultat de commande ou de confirmation physique. Le handler protege son controle par `_control_lock` et attend `scheduler.start_cycle`; le scheduler attend ensuite la commande underlying. `cancel_cycle` retire les callbacks/timers mais ne conserve ni n'annule la tache de commande en cours. De plus, `control_heating` retourne avant le calcul de securite si la consigne est absente. Une mise a jour locale ne peut donc pas garantir l'arret prioritaire exige en vol ni le traitement d'un etat physique incertain avec les contrats verifies. Aucun poele reel n'a ete commande.

Les deux scenarios correspondants sont conserves en XFAIL strict dans `tests/test_services.py`. Le developpement est bloque a ce jalon : aucune correction partielle n'est presentee comme satisfaisant AC-001..010 ; il faut un contrat permettant l'observation/coordination des commandes ou une decision de perimetre compatible avec la surete.

## Complément de faisabilité : observation Duepi (2026-10-24)

Précision utilisateur : l'entité `climate` Duepi_evo est l'underlying du VTherm et Pellet Stove peut lire son état HA via `underlying_entity_ids`. Ce fait apporte une source d'observation du brûleur, mais pas un reçu corrélé à une commande.

Sémantique vérifiée dans `duepi_evo/client.py` et `climate.py` : `Off` donne le mode `off` et `heating=False`; `Cooling down` donne `heat`, `heating=False` et l'action HA `idle`; `Eco idle` donne `heat`, `heating=True` mais l'action HA `idle`; `Flame On` donne `heat` et l'action `heating`. `Ignition starting` et `Cleaning` sont des phases de transition. `Unknown state` ne constitue pas une confirmation de chauffe. Quand `coordinator.data is None`, les propriétés climate renvoient aussi `HVACMode.OFF`/`HVACAction.OFF` et des attributs nuls : ce fallback ne prouve pas que le poêle est éteint. Une observation absente, indisponible, inconnue ou incohérente doit rester « inconnue »; `heat` seul n'est pas une preuve de flamme, et `idle` n'est pas `off`.

Après un ACK Duepi, `async_set_hvac_mode` appelle `coordinator.async_request_refresh()`. Home Assistant termine le refresh, notifie les listeners du coordinator et l'entité Duepi écrit son état HA avant le retour de cette attente. Cela rend le dernier snapshot réussi observable après un appel direct bloquant; ce snapshot reste une lecture du brûleur, pas un reçu de réussite de la commande. Le handler Duepi intercepte les erreurs client et retourne sans refresh, et un échec de refresh rend l'entité indisponible : le retour normal d'un service ne suffit donc pas à établir l'état.

Blocage restant vérifié dans VTherm : `UnderlyingClimate.hass_services_async_call` appelle `hass.services.async_call` sans `blocking=True`. Le scheduler peut donc rendre la main avant que le handler Duepi termine l'ACK et son refresh. Pellet Stove n'a ni identifiant de commande, ni tâche de commande suivie, ni événement permettant de corréler le prochain snapshot à cette commande. Le dernier état HA peut décrire l'état physique observé, mais ne démontre ni la fin d'une commande en vol, ni l'ordre effectif d'un OFF prioritaire suivi d'une ancienne commande ON. Sans modifier le contrat VTherm/Duepi (explicitement hors périmètre), FR-006/AC-005 et BR-004/AC-009 ne peuvent pas être garanties sans risque; aucun test n'envoie de commande à un poêle réel.

Correction sûre livrée à ce jalon : `_resolve_options` choisit désormais l'entrée locale seule, ou l'entrée globale en l'absence d'entrée locale, puis complète avec les défauts. Le test de régression vérifie qu'une clé locale absente ne récupère pas la valeur globale. L'application des options aux handlers vivants, le contrôle à chaud, la reprise du scheduler et la publication après reload restent bloqués par le contrat décrit ci-dessus; les deux tests XFAIL stricts de reconfiguration restent des preuves rouges, et non des critères satisfaits.

## Mise à jour d'implémentation (2026-10-24)

Le périmètre local autorisé a été implémenté dans Pellet Stove. Options met à jour les handlers vivants via l'API du plugin; Reconfigurer applique les nouvelles valeurs au setup de l'entrée Pellet Stove. Le contrôleur conserve le même objet d'état et ses horodatages, ainsi que le handler, son proxy, son verrou et son scheduler. Les échéances du diagnostic sont recalculées à partir des anciens horodatages. Une entrée locale reste complète et n'hérite jamais des valeurs globales.

Le cycle de vie ne recharge plus VTherm : un unload conserve la factory; le hook public HA `async_remove_entry` ne la retire qu'après suppression effective. Un unload/reload de la plateforme sensor globale détache puis recrée les objets diagnostiques des handlers actifs. En l'absence d'une observation Duepi reconnue comme non-allumée, aucune transition automatique ON n'est permise; `Flame On` évite aussi un ON doublonné. Un seuil de sécurité dépassé peut demander OFF même sans consigne.

Les reproductions Options local avec et sans entrée globale, auparavant strictement XFAIL, sont désormais des tests verts. Des tests fakes couvrent état physique connu/inconnu, absence de commande ON en état inconnu, absence de double ON, arrêt sécurité sans cible, conservation des timestamps, échéances min-on/min-off recalculées, routing global/local et remplacement du capteur après unload simulé. Ils ne prouvent pas le comportement du poêle réel ni un ordre matériel.

Limite bloquante maintenue : le verrou de contrôle sérialise l'application avec une commande VTherm déjà attendue, et l'API VTherm/Duepi ne fournit ni tâche/résultat corrélé ni garantie d'interruption ou d'ordre des appels underlyings. La priorité OFF pendant une commande en vol n'est donc pas garantie; AC-005/009 ne sont pas déclarés satisfaits. Le minimum d'état physiquement confirmé, l'échec de Store/reprise, le contrôle HA bout en bout des quatre parcours et le symptôme initial de diagnostic vide restent à vérifier. Aucun poêle réel n'a été commandé; aucun fichier Versatile Thermostat, Duepi-evo ou heating_simulator n'a été modifié.