import { LitElement, html, css, nothing } from "https://unpkg.com/lit?module";

const VERSION = "1.0.0";
const SELECTOR_KEY_HEADER = "features";
const SELECTOR_KEY_IMAGE = "content";
const SELECTOR_KEY_COMMANDS = "actions";

class StellantisVehicleCard extends LitElement {
    static properties = {
        _hass: { state: true },
        _config: { state: true },
        _device_entities: { state: true },
        _helpers: { state: false }
    };

    static styles = css`
        .sv-row {
            display: flex;
            flex-flow: row nowrap;
            align-items: center;
            margin: 0 calc(var(--ha-space-1) * -1);
        }
        .sv-col {
            flex: 1;
            padding: var(--ha-space-1);
        }
        .sv-fc {
            display: flex;
            flex-flow: column nowrap;
            align-items: center;
        }
        .sv-fr {
            display: flex;
            flex-flow: row nowrap;
            align-items: center;
        }
        .sv-mb {
            margin-bottom: var(--entities-card-row-gap,var(--card-row-gap,8px));
        }
        .sv-pb {
            padding-bottom: var(--ha-space-1);
        }
        .sv-bb {
            border-bottom: 1px solid var(--divider-color);
        }

        .sv-entity {
            color: var(--state-icon-color);
        }
        .sv-entity span {
            color: var(--primary-text-color);
            line-height: 1.3;
        }
        .sv-entity.off {
            color: var(--state-unavailable-color);
        }

        .sv-header {
            font-size: var(--ha-font-size-xs);
            --mdc-icon-size: 16px;
        }
        .sv-header .sv-row {
            margin-top: var(--ha-space-1);
            padding-top: var(--ha-space-1);
            border-top: 1px solid var(--divider-color);
        }
        .sv-header .sv-row:first-child {
            margin-top: 0;
            padding-top: 0;
            border-top: 0;
        }

        .sv-image {
            padding-top: 70%;
            background-position: center;
            background-repeat: no-repeat;
            background-size: cover;
            position: relative;
        }
        .sv-image .sv-entity {
            position: absolute;
            font-size: var(--ha-font-size-xs);
            --mdc-icon-size: 14px;
        }
        .sv-image .sv-entity:nth-child(1) {
            top: var(--ha-space-6);
            left: var(--ha-space-2);
        }
        .sv-image .sv-entity:nth-child(2) {
            top: var(--ha-space-6);
            right: var(--ha-space-2);
        }
        .sv-image .sv-entity:nth-child(3) {
            bottom: var(--ha-space-6);
            left: var(--ha-space-2);
        }
        .sv-image .sv-entity:nth-child(4) {
            bottom: var(--ha-space-6);
            right: var(--ha-space-2);
        }
        .sv-image .sv-entity span {
            margin-left: var(--ha-space-1);
        }

        .sv-commands .sv-entity span {
            margin-left: var(--entities-card-row-gap,var(--card-row-gap,8px));
        }
    `;

    async setConfig(config) {
        if (!config.entity) {
            return nothing;
        }
        this._config = config;

        if (!this._helpers) {
            this._helpers = await window.loadCardHelpers();
        }
    }

    set hass(hass) {
        if (!this._config || !this._config.entity) {
            return nothing;
        }

        this._hass = hass;

        const device_tracker_id = this._config.entity;
        const device_tracker = this._hass.entities[device_tracker_id];

        if (!device_tracker || device_tracker.platform !== "stellantis_vehicles" || device_tracker.translation_key !== "vehicle") {
            throw new Error("Invalid entity: must be a Stellantis vehicle device_tracker");
        }

        const device_id = device_tracker.device_id;

        this._device_entities = Object.values(this._hass.entities)
            .filter(e => e.device_id === device_id)
            .reduce((acc, e) => {
                const entity = this._hass.states[e.entity_id];
                if (e.translation_key == "battery") {
                    entity.attributes.icon = "mdi:battery-" + String(Math.ceil(entity.state / 10) * 10);
                }
                acc[e.translation_key] = entity;
                return acc;
            }, {});

        // this.requestUpdate();
    }

    getCardSize() {
        return 1;
    }

    getEntityRow(entity, icon = null, custom_class = "") {
        let state_value = Number.isInteger(Number(entity.state)) ? String(Number(entity.state)) : entity.state;
        if (state_value == "unavailable") {
            state_value = "off";
        }
        const state_class = custom_class+" "+state_value.toLowerCase().replace(/\s+/g, "-");
        const state_icon = icon ? icon : (entity.attributes.icon ? entity.attributes.icon : null);
        const state_icon_el = state_icon ? html`<ha-icon icon="${state_icon}"></ha-icon>` : '';
        const state_el = ["on", "off"].includes(state_value) ? '' : html`
            <span>${state_value + (entity.attributes.unit_of_measurement ? ' '+entity.attributes.unit_of_measurement : '')}</span>
        `;
        return html`
            <div class="sv-entity ${state_class}" aria-label="${entity.attributes?.friendly_name}" title="${entity.attributes?.friendly_name}">
                ${state_icon_el}
                ${state_el}
            </div>
        `;
    }

    getHeaderBlock(){
        let defaults = true;
        let entities = ["remote_commands", "engine", "moving", "preconditioning", "temperature", "autonomy", "battery", "battery_plugged", "battery_charging", "battery_soh"];
        if (this._config[SELECTOR_KEY_HEADER] && this._config[SELECTOR_KEY_HEADER].length > 0) {
            defaults = false;
            entities = this._config[SELECTOR_KEY_HEADER];
        }
        if (entities.length < 1) {
            return nothing;
        }
        const itemsPerRow = 5;
        const rows = Array.from(
            { length: Math.ceil(entities.length / itemsPerRow) },
            (_, i) => entities.slice(i * itemsPerRow, i * itemsPerRow + itemsPerRow)
        );
        return html`
            <div class="sv-header">
                ${rows.map((row) => {
                    return html`
                        <div class="sv-row">
                            ${row.map((entity) => {
                                entity = defaults ? this._device_entities[entity] : this._hass.states[entity];
                                if (!entity){
                                    return nothing;
                                }
                                return html`${this.getEntityRow(entity, null, "sv-col sv-fc")}`;
                            })}
                        </div>
                    `;
                })}
            </div>
        `;
    }

    getImageBlock() {
        let defaults = true;
        let entities = ["mileage", "service_battery_voltage"];
        if (this._config[SELECTOR_KEY_IMAGE] && this._config[SELECTOR_KEY_IMAGE].length > 0) {
            defaults = false;
            entities = this._config[SELECTOR_KEY_IMAGE];
        }
        const vehicle = this._device_entities.vehicle;
        const vehicle_img = vehicle.attributes?.entity_picture ?? null;
        if (!vehicle_img) {
            return nothing;
        }
        const items = entities.slice(0, 4);
        return html`
            <div class="sv-image" style="background-image: url(${vehicle_img});">
                ${items.map((entity) => {
                    entity = defaults ? this._device_entities[entity] : this._hass.states[entity];
                    if (!entity){
                        return nothing;
                    }
                    return html`${this.getEntityRow(entity, null, "sv-fr")}`;
                })}
            </div>
        `;
    }

    getCommandButtonsConfig() {
        let defaults = true;
        let entities = ["wakeup", "lights", "horn", "doors_lock", "doors_unlock", "preconditioning_start", "preconditioning_stop", "charge_start", "charge_stop"];
        if (this._config[SELECTOR_KEY_COMMANDS] && this._config[SELECTOR_KEY_COMMANDS].length > 0) {
            defaults = false;
            entities = this._config[SELECTOR_KEY_COMMANDS];
        }

        const default_config = {
            type: "button",
            show_name: false,
            show_icon: true,
            show_state: false,
            tap_action: { action: "toggle" },
            hold_action: { action: "none" },
            double_tap_action: { action: "none" }
        };

        const result = {
            square: true,
            type: "grid",
            columns: 5,
            cards: []
        };

        entities.map((entity) => {
            entity = defaults ? this._device_entities[entity] : this._hass.states[entity];
            if (!entity){
                return nothing;
            }
            result.cards.push({
                ...default_config,
                entity: entity.entity_id
            });
        })

        return result;
    }

    getCommandsBlock() {
        if (!this._device_entities.remote_commands || this._device_entities.remote_commands.state == "off") {
            return nothing;
        }

        const result = this._helpers.createCardElement(this.getCommandButtonsConfig());
        result.hass = this._hass;

        return html`
            <div class="sv-commands sv-row sv-mb sv-pb sv-bb">
                ${this.getEntityRow(this._device_entities.command_status, null, "sv-col sv-fr")}
            </div>
            ${result}
        `;
    }

    render() {
        if (!this._config || !this._hass || !this._helpers || !this._device_entities || !this._device_entities.vehicle) {
            return nothing;
        }

        const vehicle = this._device_entities.vehicle;
        const vehicle_img = vehicle.attributes?.entity_picture ?? "";

        return html`
            <ha-card>
                <div class="card-content">
                    ${this.getHeaderBlock()}
                    ${this.getImageBlock()}
                    ${this.getCommandsBlock()}
                </div>
            </ha-card>
        `;
    }

    static getConfigElement() {
        return document.createElement("stellantis-vehicle-card-editor");
    }

    static getStubConfig() {
        return {
            entity: ""
        };
    }
}
customElements.define("stellantis-vehicle-card", StellantisVehicleCard);

window.customCards = window.customCards ?? [];
window.customCards.push({
    name: 'Stellantis Vehicles',
    type: 'stellantis-vehicle-card',
    preview: true,
    documentationURL: `https://github.com/andreadegiovine/homeassistant-stellantis-vehicles`,
});

class StellantisVehicleCardEditor extends LitElement {
    static properties = {
        _hass: { attribute: false },
        _config: { state: true },
    };

    set hass(hass){
        this._hass = hass;

        if (!this._schema) {
            this._schema = [
                {
                    name: "entity",
                    required: true,
                    selector: {
                        entity: {
                            domain: "device_tracker",
                            integration: "stellantis_vehicles"
                        }
                    }
                }
            ];
        }
    }

    setConfig(config) {
        this._config = config;
        this.updateEntities();
    }

    configChanged(ev) {
        const event = new Event("config-changed", {
            bubbles: true,
            composed: true,
        });
        event.detail = { config: ev.detail.value };
        this.dispatchEvent(event);
    }

    updateEntities() {
        const device_tracker_id = this._config.entity;
        if (device_tracker_id) {
            if (!this._entities || device_tracker_id !== this._device_tracker_id) {
                const device_tracker = this._hass.entities[device_tracker_id];
                const device_id = device_tracker.device_id;
                this._entities = Object.values(this._hass.entities)
                    .filter(e => e.device_id === device_id)
                    .reduce((acc, e) => {
                        acc.push(e.entity_id);
                        return acc;
                    }, []);
            }
        } else {
            this._entities = [];
            this._loaded_selectors = [];
        }
        this.updateEntitySelectors();
    }

    updateEntitySelectors(){
        if (!this._config.entity) {
            this._schema = [this._schema[0]];
        } else if (this._entities) {
            this.updateEntitySelector(SELECTOR_KEY_HEADER);
            this.updateEntitySelector(SELECTOR_KEY_IMAGE);
            this.updateEntitySelector(SELECTOR_KEY_COMMANDS, ["button"]);
        }
    }

    updateEntitySelector(selector_name, selector_domain = ["sensor", "binary_sensor"]){
        if (!this._loaded_selectors) {
            this._loaded_selectors = [];
        }
        if (!this._loaded_selectors.includes(selector_name)) {
            this._schema.push({
                name: selector_name,
                include_entities: this._entities,
                selector: {
                    entity: {
                        domain: selector_domain,
                        integration: "stellantis_vehicles",
                        multiple: true,
                        reorder: true
                    }
                }
            });
            this._loaded_selectors.push(selector_name);
        }
    }

    render() {
        if (!this._hass || !this._config){
            return nothing;
        }

        return html`
            <ha-form
                .hass=${this._hass}
                .data=${this._config}
                .schema=${this._schema}
                .computeLabel=${(schema) =>
                    this._hass.localize(`ui.panel.lovelace.editor.card.generic.${schema.name}`) || schema.name
                }
                @value-changed=${this.configChanged}
            ></ha-form>
        `;
    }
}
customElements.define("stellantis-vehicle-card-editor", StellantisVehicleCardEditor);

console.info("%cSTELLANTIS-VEHICLES-CARD: v" + VERSION, "color: green; font-weight: bold")