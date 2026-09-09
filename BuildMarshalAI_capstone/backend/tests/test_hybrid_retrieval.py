from backend.hybrid_retrieval import lexical_score, normalize_scores, search_tokens


def test_search_tokens_remove_chat_filler_but_keep_specification_terms():
    assert search_tokens("Tell me very details about Guestroom Carpet Option B") == [
        "guestroom", "carpet", "option", "b"
    ]


def test_exact_option_b_specification_outranks_option_a_and_index_page():
    query = "Tell me very details about Guestroom Carpet Option B"
    option_b = {
        "doc_name": "finish-specifications.pdf",
        "text_content": (
            "Guestroom Carpet Option B CA-001B. Style IN23277 Infinity. "
            "Guestroom Carpet Option B custom colors and 36 x 36 repeat."
        ),
    }
    option_a = {
        "doc_name": "finish-specifications.pdf",
        "text_content": "Guestroom Carpet Option A CA-001A",
    }
    index_page = {
        "doc_name": "finish-index.pdf",
        "text_content": "Guestroom Carpet Option B ........ page 4",
    }

    assert lexical_score(query, option_b) > lexical_score(query, index_page) + 2.0
    assert lexical_score(query, option_b) > lexical_score(query, option_a)


def test_normalized_retrieval_scores_are_safe_for_ui_percentages():
    scores = normalize_scores({"a": -0.15, "b": 0.3, "c": 0.8})
    assert scores["a"] == 0.0
    assert scores["c"] == 1.0
    assert all(0.0 <= score <= 1.0 for score in scores.values())
