import pytest

from schoolguard.weapons import WeaponEngine, selected_classes


def weapon(box=(.3, .3, .4, .5), confidence=.85, category="blade", label="Knife"):
    return {"kind": "weapon", "category": category, "label": label,
            "confidence": confidence, "bbox": list(box)}


def test_class_ids_are_resolved_from_checkpoint_names():
    names = {7: "Person", 19: "Knife", 44: "Handgun", 51: "Baseball bat"}
    assert selected_classes(names) == {19: "blade", 44: "firearm", 51: "blunt_object"}


def test_weapon_requires_persistent_strong_observations_and_reports_timing():
    engine = WeaponEngine()
    assert engine.update([weapon()], 0) == []
    assert engine.update([weapon((.305, .3, .405, .5))], .2) == []
    assert engine.update([weapon((.31, .3, .41, .5))], .4) == []
    alerts = engine.update([weapon((.315, .3, .415, .5))], .6)
    assert len(alerts) == 1
    assert alerts[0]["event_type"] == "weapon"
    assert alerts[0]["severity"] == "urgent"
    assert alerts[0]["details"]["onset_timestamp"] == 0
    assert alerts[0]["details"]["confirmed_timestamp"] == .6
    assert alerts[0]["details"]["temporal_observations"] == 4


def test_weapon_absence_resets_evidence_and_cooldown_prevents_spam():
    engine = WeaponEngine(cooldown=10)
    engine.update([weapon()], 0)
    engine.update([weapon()], .2)
    engine.update([weapon()], .4)
    assert len(engine.update([weapon()], .6)) == 1
    engine.update([], .8)
    assert engine.update([weapon()], 1) == []
    assert engine.update([weapon()], 1.2) == []
    assert engine.update([weapon()], 1.4) == []
    assert engine.update([weapon()], 1.6) == []


def test_weak_repeated_weapon_like_shape_does_not_alert():
    engine = WeaponEngine()
    for index in range(8):
        assert engine.update([weapon(confidence=.5)], index * .2) == []


def test_one_strong_spike_among_weak_observations_does_not_alert():
    engine = WeaponEngine()
    for index, score in enumerate((.9, .5, .5, .5, .5, .5)):
        assert engine.update([weapon(confidence=score)], index * .2) == []


def test_weapon_time_must_increase():
    engine = WeaponEngine()
    engine.update([], 0)
    with pytest.raises(ValueError):
        engine.update([], 0)
