from datetime import date
from decimal import Decimal

from app.services.afterpay_parser import is_afterpay_email, parse_afterpay

SAMPLE_HTML = """<!DOCTYPE HTML>
<html>
<head><title></title></head>
<body style="font-family:'Open Sans', Arial, sans-serif;">
<div class="container">
    <h3>Thank you for choosing Afterpay!</h3>
    <p>Your order with <strong>Bing Lee Electrics Pty Limited</strong> is confirmed.</p>
    <div>
        <h3>Your payment schedule</h3>
        <div>
            <h5><strong>FIRST PAYMENT</strong></h5>
            <h4 automation_id="email-payment1-amount">$71.50</h4>
            <p automation_id="email-payment1-date">DUE DATE: Sun, 01/11/2026</p>
            <p automation_id="email-payment1-status">&nbsp;</p>
        </div>
        <div>
            <h5><strong>SECOND PAYMENT</strong></h5>
            <h4 automation_id="email-payment2-amount">$71.50</h4>
            <p automation_id="email-payment2-date">DUE DATE: Sun, 15/11/2026</p>
            <p automation_id="email-payment2-status">&nbsp;</p>
        </div>
        <div>
            <h5><strong>THIRD PAYMENT</strong></h5>
            <h4 automation_id="email-payment3-amount">$71.50</h4>
            <p automation_id="email-payment3-date">DUE DATE: Sun, 29/11/2026</p>
            <p automation_id="email-payment3-status">&nbsp;</p>
        </div>
        <div>
            <h5><strong>FOURTH PAYMENT</strong></h5>
            <h4 automation_id="email-payment4-amount">$71.50</h4>
            <p automation_id="email-payment4-date">DUE DATE: Sun, 13/12/2026</p>
            <p automation_id="email-payment4-status">&nbsp;</p>
        </div>
        <div class="subcontainer">
            <p><span><strong>Retailer:</strong></span><span automation_id="email-retailer">&nbsp;Bing Lee Electrics Pty Limited</span></p>
            <p><span><strong>Afterpay order number:</strong></span><span automation_id="email-ordernumber">&nbsp;1016080531</span></p>
            <p><span><strong>Merchant order number:</strong></span><span automation_id="email-merchantorderid">&nbsp;BL03387269</span></p>
            <h3 automation_id="email-order-total">Total&nbsp;&nbsp;$286.00</h3>
        </div>
    </div>
</div>
</body>
</html>"""


def test_is_afterpay_email():
    assert is_afterpay_email("orders@afterpay.com", "Your order confirmation", "")
    assert is_afterpay_email("someone@example.com", "Afterpay order confirmed", "")
    assert is_afterpay_email(
        "someone@example.com", "Order confirmation", "Thank you for choosing Afterpay!"
    )
    assert not is_afterpay_email(
        "billing@energy.com", "Electricity invoice", "Amount due: $150"
    )


def test_parse_afterpay_sample_html():
    extracted = parse_afterpay(SAMPLE_HTML)
    assert extracted is not None
    assert extracted.merchant == "Bing Lee Electrics Pty Limited"
    assert extracted.order_id == "1016080531"
    assert extracted.total_amount == Decimal("286.00")
    assert extracted.installment_amount == Decimal("71.50")
    assert extracted.interval_count == 2  # fortnightly
    assert extracted.max_occurrences == 4
    assert extracted.start_date == date(2026, 11, 1)

    assert len(extracted.installments) == 4
    assert extracted.installments[0].due_date == date(2026, 11, 1)
    assert extracted.installments[1].due_date == date(2026, 11, 15)
    assert extracted.installments[2].due_date == date(2026, 11, 29)
    assert extracted.installments[3].due_date == date(2026, 12, 13)


def test_parse_afterpay_text_fallback():
    text = """
    Thank you for choosing Afterpay!
    Your order with Kmart Australia is confirmed.
    Afterpay order number: 987654321
    FIRST PAYMENT $25.00 DUE DATE: Sun, 01/11/2026
    SECOND PAYMENT $25.00 DUE DATE: Sun, 15/11/2026
    THIRD PAYMENT $25.00 DUE DATE: Sun, 29/11/2026
    FOURTH PAYMENT $25.00 DUE DATE: Sun, 13/12/2026
    Total $100.00
    """
    extracted = parse_afterpay("", text_body=text)
    assert extracted is not None
    assert extracted.merchant == "Kmart Australia"
    assert extracted.order_id == "987654321"
    assert extracted.installment_amount == Decimal("25.00")
    assert extracted.interval_count == 2
    assert extracted.max_occurrences == 4
    assert extracted.start_date == date(2026, 11, 1)
