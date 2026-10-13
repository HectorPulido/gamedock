"""Admin-owned Selkies limits and compatibility with saved game profiles."""
import unittest
from runtime.streaming import STREAMING_DEFAULTS, STREAMING_PRESETS, LEGACY_FIELDS, validate_streaming, selkies_environment

class Streaming(unittest.TestCase):
    def test_presets_pin_backend_and_leave_browser_preferences_local(self):
        for preset in STREAMING_PRESETS.values():
            cfg=validate_streaming(preset,complete=True)
            env=selkies_environment(cfg,'1280x720')
            self.assertEqual(env['SELKIES_FRAMERATE'],f"{cfg['refresh_rate']}-{cfg['refresh_rate']}")
            self.assertEqual(env['SELKIES_MANUAL_WIDTH'],'1280')
            self.assertEqual(env['SELKIES_MANUAL_HEIGHT'],'720')
            self.assertEqual(env['SELKIES_ENABLE_RESIZE'],'false|locked')
            self.assertFalse(any(k.startswith('XPRA_') for k in env))
        baseline=selkies_environment({},'1280x720')
        for values in ({'canvas_filter':'crisp'},{'canvas_filter':'fsr'},{'viewer_scale':'integer'},{'restore_focus':False}):
            self.assertEqual(selkies_environment(values,'1280x720'),baseline)

    def test_admin_audio_and_video_limits_are_honored(self):
        env=selkies_environment({'bandwidth_mbps':4,'refresh_rate':24,'rate_control':'crf','video_crf':18,'audio_enabled':False,'audio_bitrate':'64'},'1066x600')
        self.assertEqual(env['SELKIES_VIDEO_BITRATE'],'4000-4000')
        self.assertEqual(env['SELKIES_FRAMERATE'],'24-24')
        self.assertEqual(env['SELKIES_VIDEO_CRF'],'18-18')
        self.assertEqual(env['SELKIES_AUDIO_ENABLED'],'false|locked')
        self.assertEqual(env['SELKIES_AUDIO_BITRATE'],'64000')
        self.assertEqual(env['SELKIES_MANUAL_WIDTH'],'1066')
        self.assertEqual(selkies_environment({'video_codec':'jpeg'},'1280x720')['SELKIES_ENCODER'],'jpeg')

    def test_saved_xpra_profiles_are_readable_and_do_not_change_backend(self):
        old={'quality':95,'min_quality':85,'idle_fix':False,'encoding':'png','encodings':'png,rgb','batch_match_refresh':False}
        self.assertEqual(selkies_environment(old,'1280x720'),selkies_environment({},'1280x720'))
        self.assertEqual(validate_streaming(old),old)
        self.assertTrue({'batch_max_delay','encoding','quality'}<=LEGACY_FIELDS)
        self.assertEqual(selkies_environment({'bandwidth_mbps':0},'1280x720')['SELKIES_VIDEO_BITRATE'],'8000-8000')

    def test_reject_invalid_values_before_starting_a_game(self):
        for value in (None,[],{'video_crf':True},{'video_crf':51},{'refresh_rate':1.5},{'bandwidth_mbps':float('nan')},{'audio_enabled':1},{'audio_bitrate':'999'},{'video_codec':'h264enc;echo hello'},{'unknown':1},{'batch_min_delay':50},{'quality':20}):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_streaming(value,complete=True)
        for size in ('1280x720;id','1x1','4000x720',None):
            with self.subTest(size=size),self.assertRaises(ValueError):selkies_environment({},size)
        self.assertEqual(validate_streaming({},complete=True),STREAMING_DEFAULTS)
