# Milestones – integrazione Leapmotor

Riepilogo del lavoro fatto per aggiungere Leapmotor all'integrazione, per poter riprendere in un secondo momento.
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

## 6. Documentazione
- `README.md`: menu, tabella marchi (Details, Brand, Credits) e solo le sezioni comuni (Installation, Screenshot, Vehicle Card, Card, Global preferences, ABRP, Contributors & Translations, Support the project). `info.md` è una copia del README (la crea anche il workflow `update_readme`).
- `docs/PSA.md`: requisiti, funzioni, OAuth2, comandi, sensori batteria ed errori PSA.
- `docs/LEAPMOTOR.md`: requisiti, funzioni, configurazione (secondo account, PIN, certificato), comandi, limiti ed errori Leapmotor.
- `images/Leapmotor.png`: logo segnaposto (scritta su sfondo nero), da sostituire con il logo ufficiale.
- La sezione "## Support the project" deve restare l'ultima del README: il workflow `update_readme` riscrive tutto ciò che la segue.

## 7. Verifiche
- Test (`pytest`): crittografia, API contro un cloud finto che verifica ogni firma (`tests/leapmotor_fakes.py`), normalizzazione dello stato, setup completo di una entry in Home Assistant, config flow, coordinator PSA, file OTP.
- Istanza Home Assistant reale con cloud finto e due veicoli: config flow, entità, card (slider, orario, comandi) ed editor verificati nel browser, sia su HA 2026.2 sia su HA 2026.11.1.
- L'URL della card ora contiene la versione completa (beta incluse): prima restava uguale tra le beta e il browser poteva continuare a usare la card vecchia.
- Sull'auto reale (diagnostica del 14/11/2026): login, lista veicoli, stato, sincronizzazione certificato, verifica PIN, comando "trova auto" e refresh del token funzionano.

## 8. Da fare / da verificare sull'auto reale
- Slider del limite e orario di ricarica segnalati come assenti nella card: su un'installazione pulita compaiono; da verificare con il modello dell'auto (su T03 non vengono creati) e dopo l'aggiornamento della card (cache del browser).
- Blocca/sblocca porte non sembra funzionare: serve lo "Stato comando" dopo la pressione e la diagnostica (permessi dell'account condiviso).
- Mai provati sull'auto: immagine veicolo, limite di ricarica, orario/switch ricarica programmata, preriscaldamento batteria, energia batteria (`dumpEnergy`), ultimo tragitto.
- Intervallo ammesso dal limite di ricarica nell'app (oggi minimo 15%).
- Traduzioni Leapmotor presenti solo in inglese e italiano.
- Possibili aggiunte: finestrini, bagagliaio, pressione gomme, avvio/arresto ricarica.

## Fonti
- Protocollo: [kerniger/leapmotor-ha](https://github.com/kerniger/leapmotor-ha) (MIT), [markoceri/leapmotor-api](https://github.com/markoceri/leapmotor-api).
- Certificato dell'app: [markoceri/leapmotor-certs](https://github.com/markoceri/leapmotor-certs).
