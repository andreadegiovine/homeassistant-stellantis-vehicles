import { LitElement, html, css, nothing } from "https://unpkg.com/lit?module";

const VERSION = "1.0.2";
const SELECTOR_KEY_HEADER = "features";
const SELECTOR_KEY_IMAGE = "content";
const SELECTOR_KEY_COMMANDS = "actions";
const SELECTOR_KEY_MAP = "map";

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
            min-width: 0;
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
        .sv-pt {
            padding-top: var(--ha-space-2);
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
            max-width: 100%;
        }
        .sv-entity span state-display {
            display: block;
            text-overflow: ellipsis;
            overflow: hidden;
            white-space: nowrap;
        }

        .sv-header {
            font-size: var(--ha-font-size-xs);
            --mdc-icon-size: 20px;
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

        this._cards = {};
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
                acc[e.translation_key] = this._hass.states[e.entity_id];
                return acc;
            }, {});

        // this.requestUpdate();
    }

    getCardSize() {
        return 1;
    }

    getIconColor(entity) {
        let color = "var(--state-icon-color)";
        if (entity.attributes?.state_class == "measurement" && entity.attributes?.unit_of_measurement == "%") {
            const level = parseInt(entity.state, 10);
            color = "var(--state-sensor-battery-low-color)";
            if (level >= 30) color = "var(--state-sensor-battery-medium-color)";
            if (level >= 70) color = "var(--state-sensor-battery-high-color)";
        } else {
            if (entity.state == "on") color = "var(--state-active-color)";
            if (entity.state == "off") color = "var(--state-inactive-color)";
            if (entity.state == "unavailable") color = "var(--state-unavailable-color)";
        }
        return color;
    }

    getEntityRow(entity, custom_class = "") {
        return html`
            <div class="sv-entity ${custom_class}" aria-label="${entity.attributes?.friendly_name}" title="${entity.attributes?.friendly_name}">
                <ha-state-icon slot="icon" .stateObj=${entity} .hass=${this._hass} style="color: ${this.getIconColor(entity)}"></ha-state-icon>
                <span><state-display .stateObj=${entity} .hass=${this._hass}></state-display></span>
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
        if (this._config["hide_"+SELECTOR_KEY_HEADER] || entities.length < 1) {
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
                                return html`${this.getEntityRow(entity, "sv-col sv-fc")}`;
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
        if (this._config["hide_"+SELECTOR_KEY_IMAGE] || !vehicle_img) {
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
                    return html`${this.getEntityRow(entity, "sv-fr")}`;
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
        if (this._config["hide_"+SELECTOR_KEY_COMMANDS] || !this._device_entities.remote_commands || this._device_entities.remote_commands.state == "off") {
            return nothing;
        }
        if (!this._cards.commands) {
            this._cards.commands = this._helpers.createCardElement(this.getCommandButtonsConfig());
        }
        this._cards.commands.hass = this._hass;

        return html`
            <div class="sv-commands sv-row sv-mb sv-pb sv-bb">
                ${this.getEntityRow(this._device_entities.command_status, "sv-col sv-fr")}
            </div>
            ${this._cards.commands}
        `;
    }

    getMapBlock() {
        if (this._config["hide_"+SELECTOR_KEY_MAP]) {
            return nothing;
        }
        if (!this._cards.map) {
            const config = {
                type: "map",
                theme_mode: "auto",
                entities: [{entity: this._device_entities.vehicle.entity_id}],
                auto_fit: true,
                aspect_ratio: "50%",
                default_zoom: 18
            };

            this._cards.map = this._helpers.createCardElement(config);
        }
        this._cards.map.hass = this._hass;
        return html`<div class="sv-pt">${this._cards.map}</div>`;
    }

    render() {
        if (!this._config || !this._hass || !this._helpers || !this._device_entities || !this._device_entities.vehicle) {
            return nothing;
        }

        return html`
            <ha-card>
                <div class="card-content">
                    ${this.getHeaderBlock()}
                    ${this.getImageBlock()}
                    ${this.getCommandsBlock()}
                    ${this.getMapBlock()}
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
    documentationURL: `https://github.com/andreadegiovine/homeassistant-stellantis-vehicles#vehicle-card`,
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
            this.updateHideInput(SELECTOR_KEY_HEADER);
            this.updateEntitySelector(SELECTOR_KEY_IMAGE);
            this.updateHideInput(SELECTOR_KEY_IMAGE);
            this.updateEntitySelector(SELECTOR_KEY_COMMANDS, ["button", "switch"]);
            this.updateHideInput(SELECTOR_KEY_COMMANDS);
            this.updateHideInput(SELECTOR_KEY_MAP, "ui.panel.lovelace.editor.card.map.name");
        }
    }

    updateHideInput(name, translation_value_path = null) {
        const input_name = "hide_" + name;
        if (!this._loaded_selectors) {
            this._loaded_selectors = [];
        }
        if (!this._loaded_selectors.includes(input_name)) {
            const config = {
                name: input_name,
                type: "boolean",
                translation_path: "ui.components.area-filter.hide",
                translation_placeholder: "area"
            };
            if (translation_value_path) {
                config.translation_value_path = translation_value_path;
            } else {
                config.translation_value = name;
            }
            this._schema.push(config);
            this._loaded_selectors.push(input_name);
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
                .computeLabel=${(schema) => {
                    let label = this._hass.localize(`ui.panel.lovelace.editor.card.generic.${schema.name}`);
                    if (schema.translation_path) {
                        let placeholder = this._hass.localize(`ui.panel.lovelace.editor.card.generic.${schema.translation_value}`);
                        if (schema.translation_value_path) {
                            placeholder = this._hass.localize(schema.translation_value_path);
                            console.log(schema.translation_value_path);
                            console.log(placeholder);
                        }
                        label = this._hass.localize(schema.translation_path, schema.translation_placeholder, placeholder);
                    }
                    return label || schema.name;
                }}
                @value-changed=${this.configChanged}
            ></ha-form>
        `;
    }
}
customElements.define("stellantis-vehicle-card-editor", StellantisVehicleCardEditor);

console.info("%cSTELLANTIS-VEHICLES-CARD: v" + VERSION, "color: green; font-weight: bold")