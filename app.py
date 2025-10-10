#!/usr/bin/env python3
import asyncio
import argparse
import logging
from amcrest_mqtt import AmcrestMqtt
from util import load_config

if __name__ == "__main__":
    # Parse command-line arguments
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "-c",
        "--config",
        required=False,
        help="Directory or file path for config.yaml (defaults to /config/config.yaml)",
    )
    args = argparser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Setup logging
    logging.basicConfig(
        format=(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
            if not config["hide_ts"]
            else "[%(levelname)s] %(name)s: %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.DEBUG if config["debug"] else logging.INFO,
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Starting amcrest2mqtt {config['version']}")
    logger.info(f"Config loaded from {config['config_from']} ({config['config_path']})")

    # Run main loop safely
    try:
        with AmcrestMqtt(config) as mqtt:
            try:
                # Prefer a clean async run, but handle nested event loops
                asyncio.run(mqtt.main_loop())
            except RuntimeError as e:
                if "asyncio.run() cannot be called from a running event loop" in str(e):
                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(mqtt.main_loop())
                else:
                    raise
    except KeyboardInterrupt:
        logger.info("Shutdown requested (Ctrl+C). Exiting gracefully...")
    except asyncio.CancelledError:
        logger.warning("Main loop cancelled.")
    except Exception as e:
        logger.exception(f"Unhandled exception in main loop: {e}")
    finally:
        try:
            if "mqtt" in locals() and hasattr(mqtt, "api") and mqtt.api:
                mqtt.api.shutdown()
        except Exception as e:
            logger.debug(f"Error during shutdown: {e}")
        logger.info("amcrest2mqtt stopped.")