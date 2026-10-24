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

**Statut : rapport valide par l'utilisateur le 2026-10-23 pour la specification et la conception ; developpement non autorise a ce stade.**