import pytest
import json
import os


def test_choose_captain_and_striker_basic():
    """Test basic captain and striker selection."""
    from biwenger.scoring import choose_captain_and_striker
    
    detail = {
        "gk": [{"id": 1, "score": 5.0, "status": "ok", "p_start": 0.9, "position": 1}],
        "def": [{"id": 2, "score": 6.0, "status": "ok", "p_start": 0.9, "position": 2}],
        "mid": [{"id": 3, "score": 7.0, "status": "ok", "p_start": 0.9, "position": 3}],
        "fwd": [{"id": 4, "score": 8.0, "status": "ok", "p_start": 0.9, "position": 4}]
    }
    
    cap, striker = choose_captain_and_striker(detail)
    
    # Captain should be highest score among safe players (8.0 from forward id 4)
    assert cap == 4
    # Striker should be highest forward among safe players (8.0 from id 4)
    assert striker == 4


def test_choose_captain_and_striker_with_price_limit():
    """Test captain selection with CAPTAIN_MAX_VALUE."""
    from biwenger.scoring import choose_captain_and_striker
    from biwenger import config as cfg
    
    original_max = cfg.CAPTAIN_MAX_VALUE
    
    try:
        # Temporarily set a price limit
        cfg.CAPTAIN_MAX_VALUE = 1000
        
        detail = {
            "gk": [{"id": 1, "score": 5.0, "status": "ok", "p_start": 0.9, "position": 1, "price": 500}],
            "def": [{"id": 2, "score": 6.0, "status": "ok", "p_start": 0.9, "position": 2, "price": 1500}],  # Too expensive
            "mid": [{"id": 3, "score": 7.0, "status": "ok", "p_start": 0.9, "position": 3, "price": 800}],
            "fwd": [{"id": 4, "score": 8.0, "status": "ok", "p_start": 0.9, "position": 4, "price": 2000}]  # Too expensive
        }
        
        cap, striker = choose_captain_and_striker(detail)
        
        # Captain should be highest score among affordable players (7.0 from mid id 3)
        assert cap == 3
        # Striker should be None since all forwards are too expensive
        assert striker is None
    finally:
        cfg.CAPTAIN_MAX_VALUE = original_max


def test_choose_captain_and_striker_p_start_filter():
    """Test that players with low p_start are excluded from captain consideration."""
    from biwenger.scoring import choose_captain_and_striker
    
    detail = {
        "gk": [{"id": 1, "score": 5.0, "status": "ok", "p_start": 0.7, "position": 1}],
        "def": [{"id": 2, "score": 6.0, "status": "ok", "p_start": 0.7, "position": 2}],
        "mid": [{"id": 3, "score": 7.0, "status": "ok", "p_start": 0.7, "position": 3}],
        "fwd": [{"id": 4, "score": 8.0, "status": "ok", "p_start": 0.7, "position": 4}]
    }
    
    cap, striker = choose_captain_and_striker(detail)
    
    # When no safe players (p_start >= 0.85), all players are considered safe
    # Captain should be highest score among all players (8.0 from forward id 4)
    assert cap == 4
    # Striker should be highest forward among safe players (8.0 from id 4)
    assert striker == 4


def test_choose_captain_and_striker_empty_detail():
    """Test choose_captain_and_striker with empty detail."""
    from biwenger.scoring import choose_captain_and_striker
    
    cap, striker = choose_captain_and_striker({})
    assert cap is None
    assert striker is None


def test_choose_captain_and_striker_duplicate_id():
    """Test that captain and striker can be selected when GK has higher score."""
    from biwenger.scoring import choose_captain_and_striker
    
    detail = {
        "gk": [{"id": 1, "score": 6.0, "status": "ok", "p_start": 0.9, "position": 1}],
        "def": [],
        "mid": [],
        "fwd": [{"id": 2, "score": 5.0, "status": "ok", "p_start": 0.9, "position": 4}]
    }
    
    cap, striker = choose_captain_and_striker(detail)
    
    # Captain should be GK (id 1, score 6.0)
    assert cap == 1
    # Striker should be forward (id 2, score 5.0)
    assert striker == 2