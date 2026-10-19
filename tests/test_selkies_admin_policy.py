import unittest
from runtime.selkies_policy import session_environment
from runtime.streaming import selkies_environment

class AdminPolicy(unittest.TestCase):
    def test_players_keep_exact_locked_policy(self):
        self.assertEqual(session_environment({}, '960x540'), selkies_environment({}, '960x540'))
    def test_administrator_preserves_initial_values_but_can_adjust_native_controls(self):
        cfg = {'refresh_rate':30, 'bandwidth_mbps':4, 'video_codec':'jpeg', 'rate_control':'cbr'}
        env = session_environment(cfg, '960x540', admin=True)
        self.assertEqual(env['SELKIES_FRAMERATE'], '30,1-240')
        self.assertEqual(env['SELKIES_VIDEO_BITRATE'], '4000,100-1000000')
        self.assertEqual(env['SELKIES_ENCODER'].split(',')[0], 'jpeg')
        self.assertIn('h264enc', env['SELKIES_ENCODER'].split(','))
        self.assertEqual(env['SELKIES_RATE_CONTROL_MODE'], 'cbr,crf')
        self.assertEqual(env['SELKIES_UI_SHOW_SIDEBAR'], 'true')
        self.assertEqual(env['SELKIES_ENABLE_RESIZE'], 'true')
        self.assertEqual(env['SELKIES_MANUAL_WIDTH'], '960')
        self.assertEqual(env['SELKIES_MANUAL_HEIGHT'], '540')
        self.assertEqual(env['SELKIES_MANUAL_RESOLUTION'], 'true')
        self.assertEqual(env['SELKIES_FILE_TRANSFERS'], 'upload,download')
        self.assertFalse(any('|locked' in value for value in env.values()))

if __name__ == '__main__':
    unittest.main()
