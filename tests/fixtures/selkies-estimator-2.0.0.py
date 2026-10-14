# Native Selkies 2.0.0 estimator fixture from the pinned runtime image.
class NativeEstimator:
    def _estimate_client_fps(self, display_state: dict, acked_id: int,
                             configured_fps: Union[int, float], now: float) -> float:
        """Measured client FPS from acked-frame cadence, clamped to `[1.0, configured_fps]`.

        Sizes the backpressure window so a client rendering below the
        configured rate gets a correctly scaled one. The estimate updates only
        from healthy (unthrottled) intervals with forward progress and holds
        otherwise: during active backpressure the ack rate reflects the
        throttling, not the client, and following it would latch low fps ->
        tighter window -> stuck backpressure. `now` is passed in so the
        estimator is deterministic to test.
        """
        prev_id = display_state.get('_fps_sample_acked')
        prev_t = display_state.get('_fps_sample_time')
        est = display_state.get('_measured_client_fps', float(configured_fps))
        sending = display_state.get('backpressure_enabled', True)
        if prev_id is None or prev_t is None:
            display_state['_fps_sample_acked'] = acked_id
            display_state['_fps_sample_time'] = now
            display_state['_measured_client_fps'] = float(configured_fps)
            return float(configured_fps)
        dt = now - prev_t
        if dt >= 0.25:
            # Circular forward distance over the uint16 ack space.
            delta = (acked_id - prev_id) % (MAX_UINT16_FRAME_ID + 1)
            display_state['_fps_sample_acked'] = acked_id
            display_state['_fps_sample_time'] = now
            if sending and 0 < delta <= FRAME_ID_SUSPICIOUS_GAP_THRESHOLD:
                inst = delta / dt
                est = 0.4 * inst + 0.6 * est
        est = max(1.0, min(est, float(configured_fps)))
        display_state['_measured_client_fps'] = est
        return est
