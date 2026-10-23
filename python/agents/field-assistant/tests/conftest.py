import pytest

from field_assistant import field, store

OWNER = "rep@example.com"


@pytest.fixture(autouse=True)
def tmp_store(tmp_path):
    """Every test gets an empty local store."""
    s = store.LocalStore(tmp_path)
    store.set_store(s)
    yield s
    store.set_store(None)


@pytest.fixture
def business():
    return field.save_business(
        OWNER,
        {
            "name": "Sandbar Salon",
            "street": "1526 3rd St N",
            "city": "Jacksonville Beach",
            "zip": "32250",
            "phone": "904-555-0100",
        },
    )
