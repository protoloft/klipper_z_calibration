import importlib
import sys
import types
import unittest

from fakes import FakeConfig, FakeMCUEndstop, FakePrinter


sys.modules['mcu'] = types.SimpleNamespace(MCU_endstop=FakeMCUEndstop)
klipper_compat = importlib.import_module('klipper_compat')


class PrinterObjectCompatTest(unittest.TestCase):
    def test_lookup_required_objects(self):
        printer = FakePrinter()
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIs(compat.lookup_gcode(), printer.gcode)
        self.assertIs(compat.lookup_gcode_move(), printer.gcode_move)
        self.assertIs(compat.lookup_homing(), printer.homing)
        self.assertIs(compat.lookup_toolhead(), printer.toolhead)
        self.assertIs(compat.lookup_probe(), printer.objects['probe'])

    def test_lookup_optional_objects_returns_none_when_absent(self):
        printer = FakePrinter()
        printer.objects.pop('probe')
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIsNone(compat.lookup_optional_probe())
        self.assertIsNone(compat.lookup_safe_z_home())
        self.assertIsNone(compat.lookup_bed_mesh())

    def test_lookup_required_probe_keeps_printer_error_behavior(self):
        printer = FakePrinter()
        printer.objects.pop('probe')
        compat = klipper_compat.PrinterObjectCompat(printer)
        with self.assertRaises(KeyError):
            compat.lookup_probe()

    def test_load_startup_objects(self):
        printer = FakePrinter()
        config = FakeConfig(printer)
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIs(compat.load_gcode_macro(config), printer.gcode_macro)
        self.assertIs(compat.load_query_endstops(config),
                      printer.query_endstops)


if __name__ == '__main__':
    unittest.main()
