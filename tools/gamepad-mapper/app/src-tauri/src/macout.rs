use crate::engine::Out;
use core_graphics::event::{
    CGEvent, CGEventFlags, CGEventTapLocation, CGEventType, CGMouseButton, ScrollEventUnit,
};
use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};
use core_graphics::geometry::CGPoint;

pub struct MacOut;

impl MacOut {
    pub fn new() -> Self { MacOut }
    fn src() -> Option<CGEventSource> {
        CGEventSource::new(CGEventSourceStateID::HIDSystemState).ok()
    }
}

fn keycode(name: &str) -> Option<u16> {
    let n = name.trim().to_lowercase();
    let map: &[(&str, u16)] = &[
        ("a", 0), ("b", 11), ("c", 8), ("d", 2), ("e", 14), ("f", 3), ("g", 5), ("h", 4),
        ("i", 34), ("j", 38), ("k", 40), ("l", 37), ("m", 46), ("n", 45), ("o", 31), ("p", 35),
        ("q", 12), ("r", 15), ("s", 1), ("t", 17), ("u", 32), ("v", 9), ("w", 13), ("x", 7),
        ("y", 16), ("z", 6), ("0", 29), ("1", 18), ("2", 19), ("3", 20), ("4", 21), ("5", 23),
        ("6", 22), ("7", 26), ("8", 28), ("9", 25), ("space", 49), ("return", 36), ("tab", 48),
        ("escape", 53), ("backspace", 51), ("forwarddelete", 117), ("up", 126), ("down", 125),
        ("left", 123), ("right", 124), ("home", 115), ("end", 119), ("pageup", 116),
        ("pagedown", 121), ("minus", 27), ("equals", 24), ("comma", 43), ("period", 47),
        ("slash", 44), ("semicolon", 41), ("quote", 39), ("leftbracket", 33), ("rightbracket", 30),
        ("backslash", 42), ("grave", 50), ("f1", 122), ("f2", 120), ("f3", 99), ("f4", 118),
        ("f5", 96), ("f6", 97), ("f7", 98), ("f8", 100), ("f9", 101), ("f10", 109), ("f11", 103),
        ("f12", 111), ("shift", 56), ("control", 59), ("ctrl", 59), ("option", 58), ("alt", 58),
        ("command", 55), ("cmd", 55), ("capslock", 57),
    ];
    map.iter().find(|(k, _)| *k == n).map(|(_, v)| *v)
}

fn mbtn(b: &str) -> (CGEventType, CGEventType, CGMouseButton) {
    match b {
        "right" => (CGEventType::RightMouseDown, CGEventType::RightMouseUp, CGMouseButton::Right),
        "middle" => (CGEventType::OtherMouseDown, CGEventType::OtherMouseUp, CGMouseButton::Center),
        _ => (CGEventType::LeftMouseDown, CGEventType::LeftMouseUp, CGMouseButton::Left),
    }
}

fn cur_loc() -> CGPoint {
    MacOut::src()
        .and_then(|s| CGEvent::new(s).ok())
        .map(|e| e.location())
        .unwrap_or(CGPoint::new(0.0, 0.0))
}

impl Out for MacOut {
    fn key(&mut self, key: &str, flags: u64, down: bool) {
        if let (Some(kc), Some(src)) = (keycode(key), MacOut::src()) {
            if let Ok(ev) = CGEvent::new_keyboard_event(src, kc, down) {
                ev.set_flags(CGEventFlags::from_bits_truncate(flags));
                ev.post(CGEventTapLocation::HID);
            }
        }
    }
    fn key_tap(&mut self, key: &str, flags: u64) {
        self.key(key, flags, true);
        self.key(key, flags, false);
    }
    fn mouse(&mut self, button: &str, down: bool, flags: u64) {
        let (d, u, b) = mbtn(button);
        if let Some(src) = MacOut::src() {
            let ty = if down { d } else { u };
            if let Ok(ev) = CGEvent::new_mouse_event(src, ty, cur_loc(), b) {
                ev.set_flags(CGEventFlags::from_bits_truncate(flags));
                ev.post(CGEventTapLocation::HID);
            }
        }
    }
    fn mouse_tap(&mut self, button: &str, flags: u64) {
        self.mouse(button, true, flags);
        self.mouse(button, false, flags);
    }
    fn scroll(&mut self, amount: i32) {
        if let Some(src) = MacOut::src() {
            if let Ok(ev) = CGEvent::new_scroll_event(src, ScrollEventUnit::LINE, 1, amount, 0, 0) {
                ev.post(CGEventTapLocation::HID);
            }
        }
    }
    fn move_cursor(&mut self, dx: f64, dy: f64, held: Option<&str>) {
        let loc = cur_loc();
        let np = CGPoint::new(loc.x + dx, loc.y + dy);
        let ty = match held {
            Some("left") => CGEventType::LeftMouseDragged,
            Some("right") => CGEventType::RightMouseDragged,
            Some(_) => CGEventType::OtherMouseDragged,
            None => CGEventType::MouseMoved,
        };
        if let Some(src) = MacOut::src() {
            if let Ok(ev) = CGEvent::new_mouse_event(src, ty, np, CGMouseButton::Left) {
                ev.post(CGEventTapLocation::HID);
            }
        }
    }
}
