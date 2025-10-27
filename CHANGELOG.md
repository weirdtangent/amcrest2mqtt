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
