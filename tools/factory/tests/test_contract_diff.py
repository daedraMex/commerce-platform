from factory.contract_diff import touched_contract_ids, undeclared_contracts
from factory.tickets import Contracts

# What `git diff --unified=100000 origin/main -- docs/contracts/` gives: the whole
# file as context, so every changed line has its section heading above it.
HEADER = (
    "diff --git a/docs/contracts/photos.md b/docs/contracts/photos.md\n"
    "index 1111111..2222222 100644\n"
    "--- a/docs/contracts/photos.md\n"
    "+++ b/docs/contracts/photos.md\n"
    "@@ -1,20 +1,21 @@\n"
)


def test_an_edit_in_the_middle_of_a_section_names_that_section():
    diff = HEADER + (
        " # Photos contracts\n"
        " \n"
        " Intro text, outside any contract.\n"
        " \n"
        " ## photos.process-photo-task\n"
        " \n"
        " | Retries | up to 3 |\n"
        " \n"
        " ## photos.catalog-port\n"
        " \n"
        " | `get_media(store, media_id)` | `MediaRecord` |\n"
        "+| `reorder_carousel(store, *, product_id, image_ids)` | see below |\n"
        " | `remove_from_carousel(...)` | see below |\n"
        " \n"
        " ### Errors\n"
        " \n"
        "-old error text\n"
        "+new error text\n"
        " \n"
        " ## photos.submission-states\n"
        " \n"
        " States: uploaded, processing.\n"
    )

    assert touched_contract_ids(diff) == {"photos.catalog-port"}


def test_a_new_section_and_a_removed_one_are_both_named():
    diff = HEADER + (
        " # Photos contracts\n"
        " \n"
        "-## photos.old-queue\n"
        "-\n"
        "-Removed contract.\n"
        "+## photos.processing-queue\n"
        "+\n"
        "+New contract.\n"
        " \n"
        " ## photos.catalog-port\n"
        " \n"
        " Unchanged.\n"
    )

    assert touched_contract_ids(diff) == {"photos.old-queue", "photos.processing-queue"}


def test_an_edit_outside_any_contract_names_none():
    diff = HEADER + (
        " # Photos contracts\n"
        " \n"
        "-Each heading is a contract id.\n"
        "+Each heading names a contract id.\n"
        " \n"
        " ## photos.catalog-port\n"
        " \n"
        " Unchanged.\n"
        " \n"
        " ## Notes for readers\n"
        " \n"
        "+A note under a heading that is not a contract id.\n"
    )

    assert touched_contract_ids(diff) == frozenset()


def test_two_contract_files_are_read_separately():
    diff = (
        HEADER + " ## photos.catalog-port\n"
        "+changed\n"
        "diff --git a/docs/contracts/catalog.md b/docs/contracts/catalog.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/docs/contracts/catalog.md\n"
        "@@ -0,0 +1,3 @@\n"
        "+# Catalog contracts\n"
        "+\n"
        "+## catalog.product-api\n"
    )

    assert touched_contract_ids(diff) == {"photos.catalog-port", "catalog.product-api"}


def test_an_empty_diff_names_none():
    assert touched_contract_ids("") == frozenset()


def test_undeclared_contracts_say_how_the_ticket_named_them():
    declared = Contracts(
        held=frozenset({"photos.submission-states"}),
        consumed=frozenset({"photos.catalog-port"}),
    )
    touched = frozenset(
        {"photos.catalog-port", "photos.submission-states", "photos.processing-queue"}
    )

    assert undeclared_contracts(touched, declared) == (
        ("photos.catalog-port", "declared as consumed"),
        ("photos.processing-queue", "not declared"),
    )
