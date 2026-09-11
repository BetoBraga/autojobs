from inspect import getsource

from app import OnboardingWizard, ScreenRect, find_onboarding_position


def test_onboarding_guide_is_placed_outside_the_highlighted_area():
    screen = ScreenRect(0, 0, 1920, 1080)
    focus = ScreenRect(440, 280, 500, 280)

    position = find_onboarding_position(screen, focus, 640, 280)

    assert position is not None
    assert screen.contains(position)
    assert not position.intersects(focus)


def test_onboarding_guide_uses_vertical_space_when_a_target_spans_the_window_width():
    screen = ScreenRect(0, 0, 1366, 768)
    focus = ScreenRect(40, 240, 1286, 130)

    position = find_onboarding_position(screen, focus, 640, 280)

    assert position is not None
    assert screen.contains(position)
    assert not position.intersects(focus)


def test_onboarding_guide_has_no_overlapping_fallback_when_the_screen_is_full():
    screen = ScreenRect(0, 0, 800, 600)
    focus = ScreenRect(0, 0, 800, 600)

    assert find_onboarding_position(screen, focus, 640, 280) is None


def test_window_frame_clearance_prevents_a_titlebar_collision_with_the_focus():
    screen = ScreenRect(-1920, 0, 3840, 1080)
    focus = ScreenRect(147, 329, 469, 229)

    placement = find_onboarding_position(screen, focus, 680, 296, margin=28)

    assert placement is not None
    content_rect = ScreenRect(placement.x + 8, placement.y + 31, 660, 252)
    assert not content_rect.intersects(focus)


def test_wizard_reserves_space_for_the_native_window_frame():
    source = getsource(OnboardingWizard._position_next_to_focus)

    assert "outer_width = width + 20" in source
    assert "outer_height = height + 44" in source
    assert "find_onboarding_position(screen, self._focus_rect, outer_width, outer_height" in source