# Standard library
import pathlib
import logging

# Third party library
import pytest

# Local library
import monitor_dc_temp

class TestClass:
    """
    Testing the monitoring code
    """

    def setup_class(self):
        self.mon = monitor_dc_temp.MonitorDCTemp()

    def test_log_levels(self):
        assert self.mon.logger.level == 0
        self.mon.set_debug()
        assert self.mon.logger.level == 10

    def test_log_locations(self):
        location = self.mon.location.joinpath('log').joinpath(f"{self.mon.name}.log")
        assert pathlib.Path.is_file(location) is True

    def test_log_contents(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="capturing"):
            self.mon.msg("testing")
        assert 'testing' in caplog.text

    def test_notify(self):
        assert self.mon.notify() is True

    def test_set_location(self):
        assert self.mon.set_location() is True
        assert self.mon.set_location(zip="fail") is False

    def test_get_blocking_weather(self):
        assert self.mon.get_blocking_weather() is True
        self.mon.lon = "fail"
        assert self.mon.get_blocking_weather() is False
