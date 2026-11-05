from app.utils.text import extract_note, extract_request, find_wake_word, request_is_complete

WW = ["navi", "návi", "navy", "nabi"]


def test_wake_at_start_and_request():
    text = "Navi, lembre-se de validar o contrato com o fornecedor."
    assert find_wake_word(text, WW) == (0, 4)
    assert extract_request(text, WW) == "lembre-se de validar o contrato com o fornecedor."


def test_wake_with_accent_and_vocative_in_second_position():
    text = "Então Návi, o que você acha dessa proposta?"
    assert find_wake_word(text, WW) is not None
    assert extract_request(text, WW) == "o que você acha dessa proposta?"


def test_wake_at_end_keeps_full_sentence():
    text = "O que você acha disso, Navi?"
    assert extract_request(text, WW) == text


def test_third_person_mentions_are_ignored():
    assert find_wake_word("fala com a Navi depois", WW) is None
    assert find_wake_word("a Navi vai anotar isso depois, pode deixar", WW) is None
    assert find_wake_word("Pergunta pra Navi", WW) is None


def test_mid_sentence_mention_is_ignored():
    assert find_wake_word("eu acho que o nome Navi ficou bom para o produto, certo?", WW) is None


def test_incomplete_request_is_pending():
    assert request_is_complete(extract_request("Navi,", WW)) is False
    assert request_is_complete(extract_request("Navi, resume o que decidimos", WW)) is True


def test_note_extraction_variants():
    assert extract_note("lembre-se de validar o contrato com o fornecedor.") == "validar o contrato com o fornecedor"
    assert extract_note("anota aí: revisar o orçamento até sexta") == "revisar o orçamento até sexta"
    assert extract_note("não esqueça de cobrar o João") == "cobrar o João"
    assert extract_note("não se esqueça que o prazo é dia 20") == "o prazo é dia 20"
    assert extract_note("o que você acha dessa proposta?") is None
