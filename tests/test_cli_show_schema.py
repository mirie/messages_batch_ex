"""show-schema prints the schema and a one-line type summary per field."""

from invoice_batch.cli import show_schema


def test_it_summarizes_each_fields_type(capsys):
    show_schema.main()
    out = capsys.readouterr().out
    assert "  is_invoice      boolean\n" in out
    assert "  due_date        string or null\n" in out
    assert "  total           number or null\n" in out
    assert "  line_items      array\n" in out
