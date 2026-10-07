"""Restore rolling histories with one validation/conversion pass per event."""
import math
from collections import deque
from build_prospective_history import History


def restore_history(value):
    if value['config'] != {'kind': 'window', 'days': 1095}:
        raise ValueError('Unexpected history window')
    result = History(value['config'])
    today = result.today = value['today']
    for key, is_tuple, state, events in value['records']:
        key = tuple(key) if is_tuple else key
        if key in result.states or len(state) != 3:
            raise ValueError('Invalid serialized history')
        if not (math.isfinite(state[0]) and math.isfinite(state[1]) and math.isfinite(state[2])):
            raise ValueError('Invalid serialized history')
        if state[0] != len(events): raise ValueError('History totals differ from events')
        if state[2] > today: raise ValueError('History contains future events')
        queue = deque(); total = 0.; previous = None
        for event in events:
            if len(event) != 2: raise ValueError('Invalid history event')
            day, outcome = event
            if not math.isfinite(day) or not math.isfinite(outcome): raise ValueError('Nonfinite history event')
            if day > today or (previous is not None and day < previous):
                raise ValueError('History contains future or unordered events')
            total += outcome; previous = day
            queue.append((day, outcome))
        if abs(state[1]-total) > 1e-8: raise ValueError('History totals differ from events')
        result.states[key] = list(state)
        result.events[key] = queue
    return result
