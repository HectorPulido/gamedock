import unittest
from runtime.gamepad import validate_state, Output


class ControllerTests(unittest.TestCase):
    def test_bounded_state(self):
        self.assertEqual(validate_state({})[0], [0] * 4)
        for data in [
            None,
            [],
            {"axes": [2, 0, 0, 0]},
            {"axes": [float("nan"), 0, 0, 0]},
            {"buttons": [1] * 17},
            {"axes": [0]},
            {"axes": [True] * 4},
        ]:
            with self.assertRaises(ValueError):
                validate_state(data)

    def test_keyboard_releases_and_shared_keys(self):
        class X:
            def XKeysymToKeycode(self, display, key):
                return key

            def XStringToKeysym(self, key):
                return key

            def XFlush(self, display):
                pass

        class XT:
            def __init__(self):
                self.events = []

            def XTestFakeKeyEvent(self, display, key, down, delay):
                self.events.append((key, down))

        output = Output.__new__(Output)
        output.device = None
        output.display = None
        output.held = set()
        output.x = X()
        output.xt = XT()
        buttons = [False] * 17
        buttons[1] = buttons[16] = True
        output.apply([-1, 0, 0, 0], buttons)
        self.assertCountEqual(output.xt.events, [(b"a", 1), (b"Escape", 1)])
        buttons[1] = False
        output.apply([0] * 4, buttons)
        self.assertEqual(output.xt.events[-1], (b"a", 0))
        output.apply([0] * 4, [False] * 17)
        self.assertEqual(output.xt.events[-1], (b"Escape", 0))
