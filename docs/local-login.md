# Using a local login helper

The integration can send browser-login requests to a helper you operate instead of the shared hosted service. The helper still connects to Stellantis over the internet. Vehicle data, OAuth token renewal and remote commands also depend on Stellantis; this is not an offline vehicle integration.

## Configure the address

1. Install and start a compatible login helper, such as the [Stellantis Login Worker add-on](https://github.com/ktaubmann/StellantisHAAddon/tree/main/stellantis_login_worker). Choose the login-worker add-on when keeping this HACS integration; the separate vehicle bridge is not required.
2. Use the address reachable **from Home Assistant**. For a Supervisor add-on this can be `http://<addon-hostname>:3000`. The hostname depends on the repository installation: copy the actual hostname, rather than somebody else's example. A host port does not need to be published when both services use the Supervisor network. `localhost` usually points at the Home Assistant container, not the helper.
3. For an existing account, open its **Reconfigure > Global preferences** form. Save the **Login service URL** there. This works even if the integration is waiting for reauthentication; it does not require a successful login or send your password.
4. Start reauthentication, keep the manual-method checkbox unchecked, verify the selected URL, and sign in. For a new integration, enter the helper address on the login form; it is saved with the completed setup.

A worker URL saved in Global preferences survives cancelled login flows and Home Assistant restarts. A URL edited only in the login form is retained on retries in that flow and saved when setup completes; cancelling the flow discards unsaved edits. Saving preferences does not replace existing OAuth or MQTT tokens.

If the local helper fails, credentials are not retried against the shared service. To switch services, explicitly change the URL. Only use a helper you trust: it receives the email and password needed for browser login. The integration does not retain the password in its configuration-flow data or config entry.

## Check the result

Confirm both that the helper completed authorization and that Home Assistant loaded the integration. A helper returning an authorization code alone is not proof that token exchange or integration setup succeeded. An unavailable worker should leave the login form open with an error and the same selected URL.

Existing refresh grants rejected with `invalid_grant` still need a fresh login. Reinstalling the integration, removing a desktop vehicle app or restarting repeatedly does not restore a rejected grant.

## Validation scope

A local test deployment on Home Assistant 2026.9.4 successfully completed a Peugeot login through a Supervisor-network helper in approximately ten seconds and reached the `loaded` state. That deployment combined a stable-version backport of the recovery changes with the separate refresh-serialization work from PR #672 and a local default-URL override. It is not an end-to-end test of the exact develop-branch PR or of the newly added preferences UI.

Automated tests cover saving a helper preference without authentication, preserving it on reauthentication, rejecting invalid URLs before credentials are sent, retaining a selected worker on failures, and preventing an omitted form field from selecting the public default. Natural token renewal over an extended period, provider outages, other vehicle brands and add-on architectures still need live validation.
