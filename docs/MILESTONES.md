# Milestones – integrazione Leapmotor e Uconnect

Riepilogo del lavoro fatto per aggiungere Leapmotor e Uconnect (gruppo ex FCA) all'integrazione, per poter riprendere in un secondo momento.
Branch di lavoro: `develop`.

## 1. Analisi iniziale
- Integrazioni esistenti valutate: `kerniger/leapmotor-ha` (MIT, la più completa), `markoceri/leapmotor-api` (AGPL, libreria), `leapmotor-mate`, `ha-leapmotor-gateway`, `ha-leapmotor-cn`.
- Il cloud Leapmotor (`appgateway.leapmotor-international.de`) non ha nulla in comune con quello PSA: login email/password, mTLS a due livelli (certificato dell'app + certificato dell'account), richieste firmate HMAC, solo polling REST, comandi con PIN veicolo.
- Scelte fatte:
  1. nella root restano interfacce e codice condiviso; ogni cloud ha la sua directory sotto `client/`;
  2. client Leapmotor scritto da zero (async, `aiohttp`), seguendo il protocollo documentato dal progetto MIT, senza dipendere dalla libreria AGPL;
  3. il certificato dell'app non è nel repo: viene scaricato al primo setup e salvato in `.storage/stellantis_vehicles/leapmotor/`.

## 2. Refactor (nessun cambiamento funzionale per PSA)
- `client/psa/`: client (`client.py`, ex `stellantis.py`), `const.py`, `coordinator.py`, `mqtt_event.py`, `otp/`, `configs.json`, `configs_updater/`.
- `interfaces.py`: contratto `VehiclesClient` che ogni client implementa.
- `client_base.py`: `BaseVehiclesClient` (configurazione, storage nella config entry, coordinator, notifiche, immagine veicolo, ABRP).
- `client/registry.py`: sceglie il client dal campo `client` della config entry (assente = PSA, nessuna migrazione).
- `base.py`: coordinator generico con ganci (`_fetch_vehicle_data`, `_on_status_received`, `_prepare_new_data`, `_send_remote_command`, `supports`, `diagnostics`, `has_vehicle_charge_limit`); la parte PSA (MQTT, comandi, viaggi, manutenzione) è in `client/psa/coordinator.py`.
- Ogni piattaforma crea solo le entità che il coordinator dichiara con `supports(platform, key)`; le entità specifiche di un client sono in `CLIENT_SPECIFIC_ENTITIES` (`const.py`).
- Correzione: i file OTP salvati col vecchio percorso del modulo (`...stellantis_vehicles.otp`) vengono rimappati al nuovo al caricamento.

## 3. Client Leapmotor (`client/leapmotor/`)
- `const.py`: URL, valori dell'app, comandi, entità supportate.
- `crypto.py`: password del certificato account (SM4), chiave di firma (HKDF), firma richieste, cifratura PIN, device id di sessione.
- `api.py`: login, refresh token, lista veicoli, stato, immagine, piano di ricarica, comandi remoti con verifica PIN e polling dell'esito. La verifica TLS del server è disattivata (certificato self-signed).
- `certificate.py`: download, validazione e salvataggio del certificato dell'app.
- `status.py`: traduce lo stato Leapmotor (segnali numerati) nella struttura PSA letta dalle entità condivise.
- `client.py`: `LeapmotorVehicles`; password e PIN restano fuori dalla configurazione che finisce nei log.
- `coordinator.py`: comandi, piano di ricarica, ultimo tragitto.
- Config flow: "Leapmotor" nella lista delle app; email, password, PIN facoltativo (senza PIN sola lettura); reauth e riconfigurazione.

## 4. Funzioni Leapmotor
- Sensori: batteria, energia batteria, autonomia, km, velocità, temperatura esterna, stato di carica, porte, blocco, posizione, tipo, stato comando, ultima ricarica, ultimo tragitto.
- Immagine del veicolo dal pacchetto immagini dell'app, salvata in `www/stellantis_vehicles/<account>/<VIN>.png`.
- Ultimo tragitto: costruito dagli stati (Leapmotor non ha un servizio tragitti); si perde se HA si riavvia durante il tragitto.
- Comandi: blocca/sblocca, trova auto (pulsante clacson), clima on/off, preriscaldamento batteria (switch), limite di ricarica (slider, limite tenuto dall'auto, fino a 100%), ricarica programmata (orario di inizio + switch).
- Limite, orario e programmazione scrivono l'intero piano di ricarica cambiando solo il valore richiesto; la modifica è mostrata subito, mantenuta finché l'auto non la riporta e annullata se l'auto non la applica. Non disponibili su T03.
- Diagnostica del veicolo: modello, condiviso, permessi (`rights`) e abilità.

## 5. Card
- Slider del limite e orario di inizio ricarica usano le stesse chiavi di PSA, quindi compaiono al loro posto anche per Leapmotor.
- Editor: i selettori delle entità offrono solo quelle del veicolo scelto e vengono ricostruiti quando si cambia veicolo.
- Il componente dell'orario viene caricato dalla card (prima restava vuoto se la dashboard non aveva altre righe orario).

## 6. Client Uconnect (`client/uconnect/`)
- Gruppo ex FCA: Fiat (anche Abarth e Lancia), Jeep, Alfa Romeo, Maserati, Chrysler, Dodge, Ram; tutte le regioni della libreria (Europa, USA, Canada, Asia, America Latina): 20 combinazioni marchio/regione.
- Usa la libreria [py-uconnect](https://github.com/hass-uconnect/py-uconnect) 1.0.3 (Apache-2.0, asincrona, solo `aiohttp`) come requisito del manifest; nessun certificato né OAuth: email, password, marchio/regione, PIN facoltativo.
- `status.py` traduce `py_uconnect.Vehicle` nella struttura PSA (miglia convertite in km); `coordinator.py` crea solo i comandi supportati dal veicolo (`supported_commands`); `client.py` fa un solo refresh dell'account per tutti i veicoli (cache 30 s) e usa la sessione HTTP di Home Assistant.
- Polling ogni 5 minuti (come hass-uconnect); comandi: porte, clacson+luci, luci, clima (precondizionamento o HVAC), wakeup = deep refresh (max 6 ogni 20 min), avvio ricarica. Esito dei comandi letto dalla libreria (`wait_for_operation`).
- PIN errato: rifiuta solo il comando, non avvia la riautenticazione. Password errata: riautenticazione.
- Non ancora supportati: limite e programmi di ricarica (la libreria non legge il valore attuale), tragitti del cloud (si usa il tragitto costruito dagli stati).
- Nessun tester: tutto verificato solo con una libreria simulata.

## 7. Codice condiviso (rivisto con Uconnect)
- Il coordinator base ora ha: intervallo di polling per client (`default_update_interval`), ultimo tragitto costruito dagli stati per i client senza servizio tragitti (`builds_trips`, prima solo Leapmotor), disponibilità dei pulsanti decisa dal client (`command_available`), attesa dell'esito dei comandi (`_command_result_waiter`, `_command_not_applied`).
- Corretto: l'esito di un comando poteva arrivare prima che il comando fosse nella cronologia e andare perso (anche Leapmotor).
- Corretto: `asyncio.iscoroutinefunction` (deprecato in Python 3.14) sostituito con `inspect.iscoroutinefunction`.

## 8. Documentazione
- `README.md`: menu, tabella marchi (Details, Brand, Credits) e solo le sezioni comuni (Installation, Screenshot, Vehicle Card, Card, Global preferences, ABRP, Contributors & Translations, Support the project). `info.md` è una copia del README (la crea anche il workflow `update_readme`).
- `docs/PSA.md`: requisiti, funzioni, OAuth2, comandi, sensori batteria ed errori PSA.
- `docs/UCONNECT.md`: requisiti, funzioni, marchi e regioni, comandi, limiti ed errori Uconnect.
- `docs/LEAPMOTOR.md`: requisiti, funzioni, configurazione (secondo account, PIN, certificato), comandi, limiti ed errori Leapmotor.
- `images/Leapmotor.png`, `Fiat.png`, `Jeep.png`, `AlfaRomeo.png`, `Maserati.png`, `Chrysler.png`, `Dodge.png`, `Ram.png`: loghi segnaposto (scritta su sfondo nero), da sostituire con il logo ufficiale.
- La sezione "## Support the project" deve restare l'ultima del README: il workflow `update_readme` riscrive tutto ciò che la segue.

## 9. Verifiche
- Regressione PSA: le entità create da una entry PSA (58) confrontate con il codice di prima della sessione (commit `436cd15`), identiche; fissato in `tests/test_psa_setup.py`.
- Config flow di tutti i client (nuova entry, errori, account duplicato, riautenticazione, riconfigurazione): `tests/test_config_flow.py`.
- Test eseguiti anche con Python 3.14 e Home Assistant 2026.10.4 (il plugin di test non supporta ancora la 2026.11).
- Test (`pytest`): crittografia, API contro un cloud finto che verifica ogni firma (`tests/leapmotor_fakes.py`), normalizzazione dello stato, setup completo di una entry in Home Assistant, config flow, coordinator PSA, file OTP.
- Istanza Home Assistant reale con cloud finto e due veicoli: config flow, entità, card (slider, orario, comandi) ed editor verificati nel browser, sia su HA 2026.2 sia su HA 2026.11.1.
- L'URL della card ora contiene la versione completa (beta incluse): prima restava uguale tra le beta e il browser poteva continuare a usare la card vecchia.
- Sull'auto reale (diagnostica del 14/11/2026): login, lista veicoli, stato, sincronizzazione certificato, verifica PIN, comando "trova auto" e refresh del token funzionano.

## 10. Da fare / da verificare sull'auto reale
- Uconnect: tutto da provare su auto vere (nessun tester); in particolare quali modelli recenti su piattaforma PSA usano il cloud Uconnect.
- Slider del limite e orario di ricarica segnalati come assenti nella card: su un'installazione pulita compaiono; da verificare con il modello dell'auto (su T03 non vengono creati) e dopo l'aggiornamento della card (cache del browser).
- Blocca/sblocca porte non sembra funzionare: serve lo "Stato comando" dopo la pressione e la diagnostica (permessi dell'account condiviso).
- Mai provati sull'auto: immagine veicolo, limite di ricarica, orario/switch ricarica programmata, preriscaldamento batteria, energia batteria (`dumpEnergy`), ultimo tragitto.
- Intervallo ammesso dal limite di ricarica nell'app (oggi minimo 15%).
- Traduzioni Leapmotor presenti solo in inglese e italiano.
- Possibili aggiunte: finestrini, bagagliaio, pressione gomme, avvio/arresto ricarica.

## Fonti
- Uconnect: [py-uconnect](https://github.com/hass-uconnect/py-uconnect), [hass-uconnect](https://github.com/hass-uconnect/hass-uconnect) (Apache-2.0).
- Protocollo: [kerniger/leapmotor-ha](https://github.com/kerniger/leapmotor-ha) (MIT), [markoceri/leapmotor-api](https://github.com/markoceri/leapmotor-api).
- Certificato dell'app: [markoceri/leapmotor-certs](https://github.com/markoceri/leapmotor-certs).
