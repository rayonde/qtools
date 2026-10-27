import unittest
import math
import time
from qtools.powermeter.connection import get_device, list_available_backends
from qtools.powermeter.measurement import read, measure_power, compute_statistics
from qtools.powermeter.backends import PowerMeter, BasePowerMeter, register_backend, get_backend_class
from qtools.powermeter.backends.mock import MockPowerMeter
from qtools.powermeter.backends.s15 import S15PowerMeter


class TestPowerMeterFactory(unittest.TestCase):
    def test_factory_creation(self):
        """Test that get_device returns PowerMeter facade instances."""
        mock_dev = get_device("mock", "MOCK123")
        self.assertIsInstance(mock_dev, PowerMeter)
        self.assertIsInstance(mock_dev, BasePowerMeter)
        self.assertIsInstance(mock_dev.impl, MockPowerMeter)

        s15_dev = get_device("s15", "S15_ADDR")
        self.assertIsInstance(s15_dev, PowerMeter)
        self.assertIsInstance(s15_dev.impl, S15PowerMeter)

    def test_invalid_backend(self):
        """Test that get_device raises ValueError on unknown backend."""
        with self.assertRaises(ValueError):
            get_device("nonexistent_backend", "ADDR")

    def test_custom_backend_registration(self):
        """Test registering a custom backend using @register_backend."""
        @register_backend("dummy_test_backend")
        class DummyBackend:
            def __init__(self, port="", **kwargs):
                self.port = port
                self.connected = False

            def connect(self):
                self.connected = True
                return True

            def disconnect(self):
                self.connected = False

            def get_power(self):
                return 42.0

            def get_info(self):
                return "DummyBackend"

        self.assertIn("dummy_test_backend", list_available_backends())
        dev = get_device("dummy_test_backend", "PORT1")
        self.assertIsInstance(dev, PowerMeter)
        dev.connect()
        self.assertEqual(dev.get_power(), 42.0)
        self.assertEqual(dev.get_info(), "DummyBackend")
        dev.disconnect()


class TestMockPowerMeter(unittest.TestCase):
    def test_mock_readings(self):
        """Test mock power meter values and config through PowerMeter facade."""
        dev = PowerMeter(port="MOCK_TEST", backend="mock", base_power=0.005, noise_level=0.0)
        dev.connect()

        # Wavelength configuration
        dev.set_wavelength(633.0)
        self.assertEqual(dev.get_wavelength(), 633.0)

        # Range configuration
        dev.set_range(3)
        self.assertEqual(dev.get_range(), 3)

        # Power reading is close to base power
        power = dev.get_power()
        self.assertGreater(power, 0.0)

        dev.disconnect()


class TestMeasurement(unittest.TestCase):
    def test_read(self):
        """Test read returns list of (time, power) tuples."""
        dev = PowerMeter(port="MOCK_TEST", backend="mock", base_power=0.002, noise_level=0.01, drift_rate=0.0)
        dev.connect()

        trace = read(dev, duration=0.2, samples=10)

        dev.disconnect()

        self.assertEqual(len(trace), 10)
        self.assertIsInstance(trace, list)
        self.assertIsInstance(trace[0], tuple)
        self.assertEqual(len(trace[0]), 2)
        self.assertGreater(trace[0][0], 0.0)  # elapsed time > 0
        self.assertGreater(trace[0][1], 0.0)  # power > 0

    def test_measure_power(self):
        """Test measure_power returns (mean, std_dev) tuple."""
        dev = PowerMeter(port="MOCK_TEST", backend="mock", base_power=0.002, noise_level=0.0, drift_rate=0.0)
        dev.connect()

        mean, std_dev = measure_power(dev, duration=0.2, samples=10)

        dev.disconnect()

        self.assertIsInstance(mean, float)
        self.assertIsInstance(std_dev, float)
        self.assertGreater(mean, 0.0)
        self.assertGreaterEqual(std_dev, 0.0)

    def test_compute_statistics(self):
        """Test compute_statistics from a raw trace."""
        trace = [(0.0, 1.0), (0.1, 2.0), (0.2, 3.0)]
        stats = compute_statistics(trace, duration=0.3)

        self.assertEqual(stats["count"], 3)
        self.assertAlmostEqual(stats["mean"], 2.0)
        self.assertAlmostEqual(stats["min"], 1.0)
        self.assertAlmostEqual(stats["max"], 3.0)
        self.assertAlmostEqual(stats["max"] - stats["min"], 2.0)
        self.assertEqual(stats["duration"], 0.3)
        self.assertGreater(stats["std_dev"], 0.0)  # non-zero spread


if __name__ == "__main__":
    unittest.main()
