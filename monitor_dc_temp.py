# Standard library
import argparse
import asyncio
import inspect
import logging
import os
import pathlib
import pprint as pp
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler
from http import HTTPStatus
from typing import Optional

# Third party library
import httpx
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Reusing http client allows us to reuse a pool of TCP connections.
client = httpx.AsyncClient()


class MonitorDCTemp():
    """
    Monitor the datacenter temperature and notify at thresholds
    """

    def __init__(self, location: Optional[str] = None):
        """
        Initialize with logging
        """
        
        # Setup default values for monitoring
        if os.getenv('THRESHOLD_TEMP') is None:
            self.threshold = 90
        else:
            self.threshold = float(os.getenv('THRESHOLD_TEMP'))
        if os.getenv('SLO_TEMP') is None:
            self.slo = 300
        else:
            self.slo = int(os.getenv('SLO_TEMP'))
        self.lon = float(-73.8961)
        self.lat = float(40.7036)
        self.weather_url = os.getenv('OPENWEATHERMAP_URL')
        self.weather_key = os.getenv('OPENWEATHERMAP_KEY')
        self.slack_token = os.getenv('SLACK_TOKEN')
        if os.getenv('SEMAPHORES') is None:
            self.semaphores = 2
        else:
            self.semaphores = int(os.getenv('SEMAPHORES'))
        self.count = 0

        # Setup Log Naming and Path
        self.name = "monitor_dc_temp"
        if location is None:
            self.location = pathlib.Path().resolve()
        else:
            self.location = pathlib.Path(location)
        self.logger = logging.getLogger(self.name)

        # Setup file location
        log_location = self.location.joinpath("log")
        pathlib.Path(log_location).mkdir(exist_ok=True)
        log_file = log_location.joinpath(f"{self.name}.log")

        # Setup logging format and handlers
        formatter = logging.Formatter('%(asctime)s|%(levelname)s|%(message)s')
        
        # Stream handler
        st_handler = logging.StreamHandler(stream=None)
        st_handler.setFormatter(formatter)
        self.logger.addHandler(st_handler)
        
        # File handler
        rot_handler = RotatingFileHandler(f"{str(log_file)}", maxBytes=1024 * 1024, backupCount=2)
        rot_handler.setFormatter(formatter)
        self.logger.addHandler(rot_handler)
        #self.logger.propagate = False

    def set_debug(self, tests: bool = False) -> bool:
        """
        Enables debug output for times of trouble
        """

        self.logger.setLevel(logging.DEBUG)
        self.msg(f"Debugging output enabled {self.logger.level}")
        return True
    
    def msg(self, data: str = "", debug: bool = False) -> bool:
        """
        Helper to log messages
        """

        # Setup & Sanity
        if data == "":
            self.logger.error("Empty log message")
            return False

        # Get filename and calling func name to format message
        func_name = inspect.currentframe().f_back.f_code.co_name
        file_name = pathlib.Path(__file__).name
        msg = f"{file_name}|{func_name}: {data}"

        # Get error type and log it
        if self.logger.level == 10 and debug == True:
            self.logger.debug(msg)
        else:
            self.logger.info(msg)

        return True
    
    def notify(self, msg: str = ""):
        """
        Send a message to slack
        """
        
        self.msg("Sending slack message")
        # client = WebClient(token=self.slack_token)
        
        # try:
        #     response = client.chat_postMessage(
        #         channel="testing",
        #         text=msg
        #     )
        # except SlackApiError as e:
        #     self.msg(f"Slack failed to send message\n{e.response['error']}")

        return True

    def set_location(self, zip: int = 11385) -> bool:
        """
        Set lon and lat from zip code
        """

        try:
            location = requests.get(
                f"{self.weather_url}/geo/1.0/zip?zip={zip},US&appid={self.weather_key}", timeout=5)
            
            if location.status_code != requests.codes['ok']:
                raise Exception(f"Bad response\n{location.text}")
            
            self.lat, self.lon = location.json()['lat'], location.json()['lon']
            self.msg(f"{location.json()}", debug=True)

        except:
            self.msg(f"{traceback.format_exc()}", debug=True)
            return False

        return True
    
    def get_blocking_weather(self) -> bool:
        """
        Get weather from openweathermap.org via blocking method
        """
            
        # Get current weather
        try:
            temperature = requests.get(
                f"{self.weather_url}/data/2.5/weather?lat={self.lat}&lon={self.lon}&units=imperial&appid={self.weather_key}", 
                timeout=5
            )
            
            if temperature.status_code != requests.codes['ok']:
                raise Exception(f"Bad response\n{temperature.text}")
            
            current_temp = temperature.json()['main']['temp']
            location_name = temperature.json()['name']
            self.msg(f"{temperature.json()}", debug=True) 
        except:
            self.msg(f"{traceback.format_exc()}", debug=True)
            return False
        
        # Check for threshold and send notice
        if current_temp > self.threshold:
            note = f"Threshold of {self.threshold}F reached for {location_name} ({current_temp}F)"
            self.msg(note)
            self.notify(note)
        else:
            self.msg(f"Threshold of {self.threshold}F NOT reached for {location_name} ({current_temp}F)")
        
        return True
    
    async def counter(self, subtract: bool = False):
        if not subtract:
            self.count += 1
        elif self.count > 0:
            self.count -= 1 
    
    async def get_nonblocking_weather(self, semaphore: asyncio.Semaphore, num: int = 0):
        """
        Get weather from openweathermap.org via non blocking method
        """
        
        # Setup
        start = time.time()
        warning = False
        clearing = False
        fired = False
        
        # Get current weather but limit concurrent calls
        while True:
            async with semaphore:
                self.msg(f"Task {num} making call at {time.time()}", debug=True)
                r = await client.get(
                    f"{self.weather_url}/data/2.5/weather?lat={self.lat}&lon={self.lon}"
                    f"&units=imperial&appid={self.weather_key}",
                    timeout=5
                )
                
                # When semaphore reached, pause for some time
                if semaphore.locked():
                    self.msg(f"Concurrency limit reached, waiting...", debug=True)
                    await asyncio.sleep(10)
                    
                # Parse the data if the right status
                if r.status_code == HTTPStatus.OK:
                    current_temp = r.json()['main']['temp']
                    location_name = r.json()['name']
                    self.msg(f"{r.json()}", debug=True)
                    
                    # Check for threshold and send notice
                    # Account for (datadog does this, not needed)...
                    # * Notify on SLO being reached
                    # * Notify on SLO being cleared
                    # * Keep notifying on SLO being reached
                    # * Don't keep notifying if cleared
                    if current_temp > self.threshold:
                        await self.counter()
                        self.msg(
                            f"{self.count} count(s) of {self.threshold}F threshold "
                            f"reached at {location_name} ({current_temp}F) for {time.time() - start} seconds"
                        )
                        
                        if not warning:
                            # Initialize count warning
                            warning = True
                            clearing = False
                            start = time.time()
                            self.count = 1
                            
                        elif (warning and (time.time() - start > self.slo) and 
                              self.count > (self.semaphores * (self.slo / 10)) - 1):
                            # Reset count now that SLO has been reached and send notice
                            self.msg(f"SLO of {self.slo} seconds reached, sending notice and resetting count")
                            self.notify(
                                f"{self.count} count(s) of {self.threshold}F threshold "
                                f"reached at {location_name} ({current_temp}F) for {time.time() - start} seconds"
                            )
                            fired = True
                            warning = False
                            self.count = 0
                            
                    else:
                        await self.counter()
                        self.msg(
                            f"{self.count} count(s) of {self.threshold}F threshold has NOT "
                            f"reached at {location_name} ({current_temp}F) for {time.time() - start} seconds"
                        )
                        
                        if warning and clearing is False:
                            # Initalize count clearing
                            warning = False
                            clearing = True
                            start = time.time()
                            self.count = 1
                            
                        elif (clearing and (time.time() - start > self.slo) and 
                              self.count > (self.semaphores * (self.slo / 10)) - 1):
                            # Reset count now that SLO has been cleared and send notice
                            self.msg(f"SLO of {self.slo} seconds reached, clearing notice and resetting count")
                            if fired:
                                self.notify(
                                    f"{self.count} count(s) of {self.threshold}F threshold has NOT "
                                    f"reached at {location_name} ({current_temp}F) for {time.time() - start} seconds"
                                )
                                fired = False
                            clearing = False
                            self.count = 0
                            
                        elif fired is False and clearing is False:
                            self.count = 0
                        
                else:
                    self.msg(f"Bad response\n{r.status_code}\n{r.text}")
                
        
def parse_cmdline(args: list) -> argparse.Namespace:
    """
    Process command line argruments to script
    """

    mon = MonitorDCTemp()

    # Setup arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-v', '--verbose',
        action='store_true', default=False,
        help="Spit out debug information"
    )
    parser.add_argument(
        '-z', '--zip',
        action='store',
        help="Set geolocation from zipcode"
    )
    parser.add_argument(
        '-c', '--concurrency',
        action='store', default=2,
        help="Limit concurrency to this"
    )
    parser.add_argument(
        '-t', '--threshold',
        action='store',
        help="Threshold to monitor temperature for in fahrenheit"
    )
    parser.add_argument(
        '-o', '--once',
        action='store_true', default=False,
        help="Run the monitor once"
    )
    parser.add_argument(
        '-f', '--forever',
        action='store_true', default=False,
        help="Run the monitor forever"
    )
    
    # Define what args do
    options = parser.parse_args(args)
    if options.verbose:
        mon.set_debug()
    if options.zip:
        mon.set_location(zip=int(options.zip))
    if options.threshold:
        mon.threshold = float(options.threshold)
    if options.concurrency:
        mon.semaphores = int(options.concurrency)
    if options.once:
        mon.get_blocking_weather()
    elif options.forever:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        semaphore = asyncio.Semaphore(mon.semaphores)
        for num in range(mon.semaphores):
            loop.create_task(mon.get_nonblocking_weather(semaphore, num))
        loop.run_forever()

    return options
        
        
if __name__ == '__main__':
    parse_cmdline(sys.argv[1:])
