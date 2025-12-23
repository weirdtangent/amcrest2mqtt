# [2.4.0](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.3.3...v2.4.0) (2025-12-23)


### Bug Fixes

* add cleanup methods to protocol interface ([8c195f1](https://github.com/weirdtangent/amcrest2mqtt/commit/8c195f1eb1acb70b4461e6cd9b1d668a818860d4))


### Features

* add automatic cleanup of old media recordings ([ebe8d04](https://github.com/weirdtangent/amcrest2mqtt/commit/ebe8d04332ed1fbd861ddd62f9af8b7750a40aa1))

## [2.3.3](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.3.2...v2.3.3) (2025-11-24)


### Bug Fixes

* always try to log device_name in preference to device_id ([41ec32a](https://github.com/weirdtangent/amcrest2mqtt/commit/41ec32af471c25e4e65451363e09c83099956140))
* formatting ([cd4e1aa](https://github.com/weirdtangent/amcrest2mqtt/commit/cd4e1aa62827e14a103fdd1a1b1e96d4b3294f94))
* make sure all device_names logged are in quotes ([b0100f0](https://github.com/weirdtangent/amcrest2mqtt/commit/b0100f09318873346c82acb4cf5cfc7deee47dd0))

## [2.3.2](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.3.1...v2.3.2) (2025-11-18)


### Bug Fixes

* README.md doc on webrtc ([2531e42](https://github.com/weirdtangent/amcrest2mqtt/commit/2531e42f25fb46766a2db810701768540703bedb))

## [2.3.1](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.3.0...v2.3.1) (2025-11-18)


### Bug Fixes

* handle permission errors when saving recordings ([bf54589](https://github.com/weirdtangent/amcrest2mqtt/commit/bf54589328302ae920c9193b1880664b5bccacca))

# [2.3.0](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.2.2...v2.3.0) (2025-11-17)


### Bug Fixes

* minor linting issues ([e709760](https://github.com/weirdtangent/amcrest2mqtt/commit/e709760971cea5a087967ab46ef1d070742d4363))


### Features

* better error handling and logging ([2d48726](https://github.com/weirdtangent/amcrest2mqtt/commit/2d48726917a985b1bd190b9bdac2da9a9084d189))

## [2.2.2](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.2.1...v2.2.2) (2025-11-10)


### Bug Fixes

* save recording path as a string not Pathlib path; upgrade packages ([1231871](https://github.com/weirdtangent/amcrest2mqtt/commit/1231871ba73f27763c4feddc83760fe8f6677b36))

## [2.2.1](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.2.0...v2.2.1) (2025-11-09)


### Bug Fixes

* fix interval setting ([165d0c7](https://github.com/weirdtangent/amcrest2mqtt/commit/165d0c723fa418c79adfa05f81647dd897cb2813))

# [2.2.0](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.1.0...v2.2.0) (2025-11-08)


### Features

* **discovery:** unify service and camera discovery to new HA device schema ([8c7bfd2](https://github.com/weirdtangent/amcrest2mqtt/commit/8c7bfd2b9e462b1cf91108e4db65088cd15f893c))

# [2.1.0](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.12...v2.1.0) (2025-11-07)


### Features

* added save recordings and reboot button ([9b4338b](https://github.com/weirdtangent/amcrest2mqtt/commit/9b4338b13b37e61625b9b424bb94366616371ae6))

## [2.0.12](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.11...v2.0.12) (2025-11-06)


### Bug Fixes

* simply event for reporting to HA ([8a58519](https://github.com/weirdtangent/amcrest2mqtt/commit/8a585191a66686f1f038c3e80cc16e8833fac6f0))

## [2.0.11](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.10...v2.0.11) (2025-11-06)


### Bug Fixes

* always setup defaults for all states expected at init time ([ee05312](https://github.com/weirdtangent/amcrest2mqtt/commit/ee053122bd4c37ef365c9ee16268c35afb56a3b6))

## [2.0.10](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.9...v2.0.10) (2025-11-05)


### Bug Fixes

* return last known state if we fail to get current state, so upsert just works ([2ca75d4](https://github.com/weirdtangent/amcrest2mqtt/commit/2ca75d4128751544cc31699543032df618f92af3))

## [2.0.9](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.8...v2.0.9) (2025-11-05)


### Bug Fixes

* more generic Dockerfile; remove old/; better logging for failed /media writes ([33ab975](https://github.com/weirdtangent/amcrest2mqtt/commit/33ab97597f1f210fe6faa49020a7c313dabca658))

## [2.0.8](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.7...v2.0.8) (2025-11-04)


### Bug Fixes

* mkdir /media to prep for mounted volume ([da46ee1](https://github.com/weirdtangent/amcrest2mqtt/commit/da46ee102dc943441af0e6f1f876686682fa6474))

## [2.0.7](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.6...v2.0.7) (2025-11-04)


### Bug Fixes

* add last_device_check sensor; fix service status; only post messages on changes ([1b111b8](https://github.com/weirdtangent/amcrest2mqtt/commit/1b111b8a4ff6c704d5008e5436180a8a271f0046))

## [2.0.6](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.5...v2.0.6) (2025-11-04)


### Bug Fixes

* code cleanup; fix service sensors; reduce logging ([a414715](https://github.com/weirdtangent/amcrest2mqtt/commit/a414715f267ce3c0e21d60b74b66c8a017cf06b0))

## [2.0.5](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.4...v2.0.5) (2025-11-03)


### Bug Fixes

* add heartbeat bits and pieces ([e8ea58b](https://github.com/weirdtangent/amcrest2mqtt/commit/e8ea58b42d5c5806fa50df0a4c7a1957cd4fc757))

## [2.0.4](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.3...v2.0.4) (2025-10-29)


### Bug Fixes

* adjust server avty and states ([06e6ce2](https://github.com/weirdtangent/amcrest2mqtt/commit/06e6ce24bb7f802d4c118c7c2f85d31907be6338))

## [2.0.3](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.2...v2.0.3) (2025-10-29)


### Bug Fixes

* backoff 5+ sec for snapshot retries ([d0381e2](https://github.com/weirdtangent/amcrest2mqtt/commit/d0381e28a3f0af5593ee6741989f92c90ae1a7bf))

## [2.0.2](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.1...v2.0.2) (2025-10-29)


### Bug Fixes

* one wrong sensor state topic; allow None (null) value to be sent ([f382513](https://github.com/weirdtangent/amcrest2mqtt/commit/f38251344ee3cccb782fa18c3d6a5bc84f7ccefa))

## [2.0.1](https://github.com/weirdtangent/amcrest2mqtt/compare/v2.0.0...v2.0.1) (2025-10-27)


### Bug Fixes

* when motion goes idle, also clear region ([ec3f096](https://github.com/weirdtangent/amcrest2mqtt/commit/ec3f0962461cebde8735c675fdf847de7b06120c))

# [2.0.0](https://github.com/weirdtangent/amcrest2mqtt/compare/v1.1.0...v2.0.0) (2025-10-26)


* feat!: complete MQTT and service refactor, add timestamp + event tracking, and new modular mixins ([e230a76](https://github.com/weirdtangent/amcrest2mqtt/commit/e230a7673f114a41e98d6f5a30999f4c336cab61))


### BREAKING CHANGES

* Project layout moved to `src/amcrest2mqtt/`, internal class and import paths changed.
Users must update configs and volumes to the new structure before deploying.

# [1.1.0](https://github.com/weirdtangent/amcrest2mqtt/compare/v1.0.2...v1.1.0) (2025-10-10)


### Features

* **core:** add async process pool, graceful signal handling, and safer config loading ([f025d60](https://github.com/weirdtangent/amcrest2mqtt/commit/f025d60f75913361a13047f886ee730a9a0579df))

## [1.0.2](https://github.com/weirdtangent/amcrest2mqtt/compare/v1.0.1...v1.0.2) (2025-10-09)


### Bug Fixes

* better dns lookup ([172e939](https://github.com/weirdtangent/amcrest2mqtt/commit/172e939ec0a76c4b4b64f70a1d6d84d20b20e2fa))

## [1.0.1](https://github.com/weirdtangent/amcrest2mqtt/compare/v1.0.0...v1.0.1) (2025-10-09)


### Bug Fixes

* tls_set call for ssl mqtt connections ([53ea515](https://github.com/weirdtangent/amcrest2mqtt/commit/53ea515f005e0830dcd45e9e8bca6f7859fdc760))

# 1.0.0 (2025-10-09)


### Bug Fixes

* ensure entity_id is correct for Storage Used % entity ([f10c04b](https://github.com/weirdtangent/amcrest2mqtt/commit/f10c04b00624581feaf57c703be1f43695c674d5))
* fix doorbell entity name when device is called 'Doorbell' ([bd18f74](https://github.com/weirdtangent/amcrest2mqtt/commit/bd18f74507f0fa657d844aeefdb4e8fe2aab561e))
* move to more static Home Assistant topic names ([cfa7b00](https://github.com/weirdtangent/amcrest2mqtt/commit/cfa7b00135660cdc8dc5805c07ff234dc1d5fbec))


### Features

* semantic versioning, github action features, writes a version file, and tags Docker images ([69c4f1a](https://github.com/weirdtangent/amcrest2mqtt/commit/69c4f1ac575b2d5489000a45660211eb474dccd7))
