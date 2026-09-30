"""Adds the current request's reference to every log line."""

import contextvars
import logging

current_ref: contextvars.ContextVar[str] = contextvars.ContextVar("request_ref", default="-")


def install_record_factory() -> None:
    """Stamp every log record with the reference of the request being handled."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "adds_request_ref", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.ref = current_ref.get()
        return record

    factory.adds_request_ref = True
    logging.setLogRecordFactory(factory)


class RequestRefFilter(logging.Filter):
    """Fill in the reference for records created before the factory was installed."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach a reference if missing; never drops a record."""
        if not hasattr(record, "ref"):
            record.ref = current_ref.get()
        return True
