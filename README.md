# RO Auto Home Assistant Integration

**Important: Since only the vignette has a non-captcha API, only that one works out of the box. ITP and RCA need to be enabled separately but you will need to create and host a separate API that will parse the info from RAROM and BAAR**

`RO Auto` is a HACS custom integration that lets you track Romanian vignette status for one or multiple cars.

Each configured car creates one sensor entity in Home Assistant. The sensor exposes:

- `name`
- `make`
- `model`
- `year`
- `vin`
- `registrationNumber`
- `vignetteValid`
- `vignetteExpiryDate`

The integration fetches vignette data from:

`https://www.erovinieta.ro/vgncheck/api/findVignettes`

## Features

- Config Flow UI with support for adding one or multiple cars during setup
- Options Flow UI to add or remove cars later
- One sensor per car with full metadata as attributes
- Async polling with `DataUpdateCoordinator`

## Installation (HACS)

1. Open HACS in Home Assistant.
2. Go to **Integrations**.
3. Add this repository as a custom repository (type: **Integration**).
4. Install **RO Auto**.
5. Restart Home Assistant.
6. Add the integration from **Settings -> Devices & Services**.

## Configuration

When adding the integration:

1. Set an optional fleet name.
2. Add the first car details.
3. Enable **Add another car** to keep adding cars in the same flow.

Required car fields:

- `name`
- `make`
- `model`
- `year`
- `vin`
- `registrationNumber`

## Notes

- VIN and registration number are normalized to uppercase before requests.
- Sensor state is one of `valid`, `invalid`, or `unknown`.
- All requested car details and vignette fields are exposed as sensor attributes.
