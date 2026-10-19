"""Reject FPS samples spanning a server-imposed backpressure gate."""
import ast
from pathlib import Path

OLD = """        sending = display_state.get('backpressure_enabled', True)
        if prev_id is None or prev_t is None:"""
NEW = """        sending = display_state.get('backpressure_enabled', True)
        was_sending = display_state.get('_fps_was_sending')
        display_state['_fps_was_sending'] = sending
        if was_sending is None:
            # A live upgrade must not retain a previously feedback-degraded estimate.
            est = float(configured_fps)
        if not sending or was_sending is not True:
            # Neither a gated interval nor the interval crossing its recovery
            # boundary measures client capacity. Start a fresh healthy sample.
            display_state['_fps_sample_acked'] = acked_id
            display_state['_fps_sample_time'] = now
            est = max(1.0, min(est, float(configured_fps)))
            display_state['_measured_client_fps'] = est
            return est
        if prev_id is None or prev_t is None:"""

def patch_source(source):
    if source.count(OLD) != 1:
        raise ValueError('Unsupported Selkies FPS-estimator source contract')
    source = source.replace(OLD, NEW, 1)
    ast.parse(source)
    return source

if __name__ == '__main__':
    import selkies
    target = Path(selkies.__file__).parent / 'websockets_mode.py'
    target.write_text(patch_source(target.read_text()))
