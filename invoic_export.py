import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def validate_data(data: Dict[str, Any]) -> None:
    """Validate required fields in INVOIC data."""
    required_fields = [
        "message_ref", "invoice_number", "invoice_date",
        "parties", "items", "tax", "payment_terms"
    ]
    for field in required_fields:
        if field not in data or not data[field]:
            raise ValueError(f"Missing required field: {field}")

    if not isinstance(data["items"], list) or len(data["items"]) == 0:
        raise ValueError("INVOIC must contain at least one item.")

    logging.info("Data validation passed.")

def generate_invoic(data: Dict[str, Any], filename: str = "invoic.edi") -> str:
    """Generate an EDIFACT INVOIC message and save to a file."""
    try:
        validate_data(data)
    except ValueError as e:
        logging.error(e)
        return ""

    logging.info("Generating INVOIC message...")

    edifact = [
        "UNA:+.? '",  # Service string advice (not counted in UNT)
        f"UNH+{data['message_ref']}+INVOIC:D:96A:UN'",
        f"BGM+380+{data['invoice_number']}+9'",  # 380 = Invoice, 9 = Original
        f"DTM+137:{data['invoice_date']}:102'"
    ]

    for party in data["parties"]:
        if "qualifier" not in party or "id" not in party:
            logging.warning("Skipping invalid NAD entry: %s", party)
            continue
        edifact.append(f"NAD+{party['qualifier']}+{party['id']}::91'")

    total_amount = Decimal("0.00")
    total_tax = Decimal("0.00")

    for index, item in enumerate(data["items"], start=1):
        try:
            product_code = item["product_code"]
            description = item["description"]
            quantity = int(item["quantity"])
            price = Decimal(item["price"])
            tax_rate = Decimal(item.get("tax_rate", "0"))
        except (KeyError, ValueError, InvalidOperation, TypeError) as e:
            logging.warning("Skipping item due to error: %s | %s", e, item)
            continue

        line_total = price * quantity
        total_amount += line_total

        edifact.append(f"LIN+{index}++{product_code}:EN'")
        edifact.append(f"IMD+F++:::{description}'")
        edifact.append(f"QTY+47:{quantity}:EA'")
        edifact.append(f"PRI+AAA:{price:.2f}:EA'")

        if tax_rate > 0:
            tax_value = (line_total * tax_rate) / Decimal("100")
            total_tax += tax_value
            edifact.append(f"TAX+7+VAT+++{tax_rate:.2f}+S'")
            edifact.append(f"MOA+125:{tax_value:.2f}:'")  # Tax amount per item

    grand_total = total_amount + total_tax
    edifact.append(f"MOA+86:{total_amount:.2f}:'")  # Total before tax
    edifact.append(f"MOA+176:{total_tax:.2f}:'")    # Total tax
    edifact.append(f"MOA+9:{grand_total:.2f}:'")    # Invoice total

    if "payment_terms" in data:
        payment = data["payment_terms"]
        due_date = payment.get("due_date")
        if due_date:
            edifact.append("PAT+1++5'")  # 5 = Bank transfer
            edifact.append(f"DTM+13:{due_date}:102'")

    # UNT: Number of segments including UNH to UNT (excluding UNA)
    segment_count = len(edifact) - 1  # exclude UNA
    edifact.append(f"UNT+{segment_count}+{data['message_ref']}'")

    edifact_message = "\n".join(edifact)

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(edifact_message)
        logging.info("INVOIC message generated and saved to %s", filename)
    except OSError as e:
        logging.error("Failed to write file %s: %s", filename, e)
        return ""

    return edifact_message

# Example usage
if __name__ == "__main__":
    invoic_data = {
        "message_ref": "789123",
        "invoice_number": "INV2025001",
        "invoice_date": "20250322",
        "parties": [
            {"qualifier": "BY", "id": "123456789"},
            {"qualifier": "SU", "id": "987654321"},
            {"qualifier": "IV", "id": "555555555"}
        ],
        "items": [
            {"product_code": "ABC123", "description": "Product A", "quantity": "10", "price": "25.50", "tax_rate": "20"},
            {"product_code": "XYZ456", "description": "Product B", "quantity": "5", "price": "40.00", "tax_rate": "20"}
        ],
        "tax": {"rate": "20"},
        "payment_terms": {"due_date": "20250422"}
    }

    invoic_message = generate_invoic(invoic_data)
    if invoic_message:
        print("\nGenerated INVOIC Message:\n")
        print(invoic_message)
