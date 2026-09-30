"""The report page and its spreadsheet downloads."""

from datetime import timedelta

from django import forms
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.permissions import requires
from core.forms import AccessibleFormMixin
from reports import csv_export, data


def _date_input():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class RangeForm(AccessibleFormMixin, forms.Form):
    start = forms.DateField(label="From", widget=_date_input())
    end = forms.DateField(label="To", widget=_date_input())

    def clean(self):
        """A range that runs forwards and isn't longer than a year."""
        data_ = super().clean()
        start, end = data_.get("start"), data_.get("end")
        if start and end:
            if end < start:
                self.add_error("end", "The end date needs to be on or after the start date.")
            elif (end - start).days > data.MAX_REPORT_DAYS:
                self.add_error("end", "Please choose a year or less.")
        return data_


def _this_month():
    first = timezone.localdate().replace(day=1)
    return data.month_bounds(first)


def _form(request) -> RangeForm:
    if request.GET.get("start") or request.GET.get("end"):
        return RangeForm(request.GET)
    start, end = _this_month()
    return RangeForm({"start": start.isoformat(), "end": end.isoformat()})


@requires("view_reports")
def report(request):
    """Pick dates, then see who did what, each day, and each shift."""
    form = _form(request)
    report_ = None
    if form.is_valid():
        report_ = data.range_report(form.cleaned_data["start"], form.cleaned_data["end"])
    shortcuts = []
    first = timezone.localdate().replace(day=1)
    last_month = data.previous_month_start(first)
    for label, (start, end) in (
        ("This month", data.month_bounds(first)),
        ("Last month", data.month_bounds(last_month)),
        ("Last 4 weeks", (timezone.localdate() - timedelta(days=27), timezone.localdate())),
    ):
        shortcuts.append((label, f"?start={start.isoformat()}&end={end.isoformat()}"))
    query = f"start={form.data.get('start', '')}&end={form.data.get('end', '')}"
    return render(
        request,
        "reports/report.html",
        {"form": form, "report": report_, "shortcuts": shortcuts, "query": query},
    )


@requires("view_reports")
def download(request, table):
    """One table as a spreadsheet file."""
    if table not in csv_export.TABLES:
        raise Http404
    form = _form(request)
    if not form.is_valid():
        raise Http404
    start, end = form.cleaned_data["start"], form.cleaned_data["end"]
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="volunteers-{table}-{start.isoformat()}-to-{end.isoformat()}.csv"'
    )
    csv_export.write(table, data.range_report(start, end), response)
    return response
