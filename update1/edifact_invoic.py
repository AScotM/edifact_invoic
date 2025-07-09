import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional

# Constants for EDIFACT codes
INVOIC_DOCUMENT_TYPE = "380"
ORIGINAL_DOCUMENT = "9"
VAT_TAX_CATEGORY = "VAT"
BANK_TRANSFER_PAYMENT = "5"
DEFAULT_EDI_VERSION = "D:96A:UN"

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class EDIFACTGeneratorError(Exception):
    """Custom exception for EDIFACT generation errors"""
    pass

def validate_date(date_str: str, date_format: str = "%Y%m%d") -> bool:
    """Validate date format"""
    try:
        datetime.datetime.strptime(date_str, date_format)
        return True
    except ValueError:
        return False

def validate_decimal(value: Any) -> bool:
    """Validate decimal value"""
    try:
        Decimal(str(value))
        return True
    except (InvalidOperation, TypeError):
        return False

def validate_positive_number(value: Any) -> bool:
    """Validate positive number"""
    try:
        num = Decimal(str(value))
        return num >= 0
    except (InvalidOperation, TypeError):
        return False

def validate_data(data: Dict[str, Any]) -> None:
    """Validate required fields and data types in INVOIC data."""
    required_fields = {
        "message_ref": str,
        "invoice_number": str,
        "invoice_date": str,
        "parties": list,
        "items": list,
        "tax": dict,
        "payment_terms": dict
    }

    # Check required fields exist
    for field, field_type in required_fields.items():
        if field not in data:
            raise EDIFACTGeneratorError(f"Missing required field: {field}")
        if not isinstance(data[field], field_type):
            raise EDIFACTGeneratorError(f"Field {field} must be {field_type.__name__}")
        if not data[field]:  # Check not empty
            raise EDIFACTGeneratorError(f"Field {field} cannot be empty")

    # Validate dates
    if not validate_date(data["invoice_date"]):
        raise EDIFACTGeneratorError("Invalid invoice_date format. Expected YYYYMMDD")

    # Validate parties
    for party in data["parties"]:
        if "qualifier" not in party or "id" not in party:
            raise EDIFACTGeneratorError("Each party must have 'qualifier' and 'id'")
        if not isinstance(party["qualifier"], str) or not isinstance(party["id"], str):
            raise EDIFACTGeneratorError("Party qualifier and id must be strings")

    # Validate items
    if len(data["items"]) == 0:
        raise EDIFACTGeneratorError("INVOIC must contain at least one item")

    for item in data["items"]:
        required_item_fields = ["product_code", "description", "quantity", "price"]
        for field in required_item_fields:
            if field not in item:
                raise EDIFACTGeneratorError(f"Item missing required field: {field}")

        if not validate_positive_number(item["quantity"]):
            raise EDIFACTGeneratorError(f"Invalid quantity: {item['quantity']}")
        if not validate_positive_number(item["price"]):
            raise EDIFACTGeneratorError(f"Invalid price: {item['price']}")
        if "tax_rate" in item and not validate_positive_number(item["tax_rate"]):
            raise EDIFACTGeneratorError(f"Invalid tax_rate: {item['tax_rate']}")

    # Validate payment terms
    if "due_date" in data["payment_terms"]:
        if not validate_date(data["payment_terms"]["due_date"]):
            raise EDIFACTGeneratorError("Invalid due_date format. Expected YYYYMMDD")

    logger.info("Data validation passed")

def generate_invoic(
    data: Dict[str, Any],
    filename: Optional[str] = None,
    edi_version: str = DEFAULT_EDI_VERSION,
    character_set: str = "UNOA"
) -> str:
    """
    Generate an EDIFACT INVOIC message and optionally save to a file.
    
    Args:
        data: Dictionary containing invoice data
        filename: Optional filename to save the EDI message
        edi_version: EDI version syntax (default: 'D:96A:UN')
        character_set: Character set identifier (default: 'UNOA')
    
    Returns:
        Generated EDIFACT message as string
    """
    try:
        validate_data(data)
    except EDIFACTGeneratorError as e:
        logger.error("Validation failed: %s", e)
        raise

    logger.info("Generating INVOIC message...")

    # Build segments
    segments = [
        f"UNA:+.? '",  # Service string advice
        f"UNH+{data['message_ref']}+INVOIC:{edi_version}:{character_set}'",
        f"BGM+{INVOIC_DOCUMENT_TYPE}+{data['invoice_number']}+{ORIGINAL_DOCUMENT}'",
        f"DTM+137:{data['invoice_date']}:102'"
    ]

    # Add parties (NAD segments)
    for party in data["parties"]:
        segments.append(f"NAD+{party['qualifier']}+{party['id']}::91'")

    # Process items
    total_amount = Decimal("0.00")
    total_tax = Decimal("0.00")

    for index, item in enumerate(data["items"], start=1):
        try:
            quantity = int(item["quantity"])
            price = Decimal(str(item["price"]))
            tax_rate = Decimal(str(item.get("tax_rate", "0")))
            
            line_total = price * quantity
            total_amount += line_total

            # Add item segments
            segments.extend([
                f"LIN+{index}++{item['product_code']}:EN'",
                f"IMD+F++:::{item['description']}'",
                f"QTY+47:{quantity}:EA'",
                f"PRI+AAA:{price:.2f}:EA'"
            ])

            # Add tax segments if applicable
            if tax_rate > 0:
                tax_value = (line_total * tax_rate) / Decimal("100")
                total_tax += tax_value
                segments.extend([
                    f"TAX+7+{VAT_TAX_CATEGORY}+++{tax_rate:.2f}+S'",
                    f"MOA+125:{tax_value:.2f}:'"  # Tax amount per item
                ])

        except (ValueError, InvalidOperation) as e:
            logger.error("Error processing item %d: %s", index, e)
            raise EDIFACTGeneratorError(f"Invalid item data at position {index}") from e

    # Add monetary totals
    grand_total = total_amount + total_tax
    segments.extend([
        f"MOA+86:{total_amount:.2f}:'",  # Total before tax
        f"MOA+176:{total_tax:.2f}:'",    # Total tax
        f"MOA+9:{grand_total:.2f}:'"      # Invoice total
    ])

    # Add payment terms if available
    if "due_date" in data["payment_terms"]:
        segments.extend([
            f"PAT+1++{BANK_TRANSFER_PAYMENT}'",
            f"DTM+13:{data['payment_terms']['due_date']}:102'"
        ])

    # Add message trailer
    segment_count = len(segments) - 1  # Exclude UNA segment
    segments.append(f"UNT+{segment_count}+{data['message_ref']}'")

    # Combine segments into message
    edifact_message = "\n".join(segments)

    # Save to file if filename provided
    if filename:
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(edifact_message)
            logger.info("INVOIC message saved to %s", filename)
        except OSError as e:
            logger.error("Failed to write file %s: %s", filename, e)
            raise EDIFACTGeneratorError(f"File write error: {e}") from e

    return edifact_message

def generate_example_invoic() -> Dict[str, Any]:
    """Generate example INVOIC data for testing"""
    return {
        "message_ref": "789123",
        "invoice_number": "INV2025001",
        "invoice_date": "20250322",
        "parties": [
            {"qualifier": "BY", "id": "123456789"},  # Buyer
            {"qualifier": "SU", "id": "987654321"},  # Supplier
            {"qualifier": "IV", "id": "555555555"}   # Invoicee
        ],
        "items": [
            {
                "product_code": "ABC123",
                "description": "Premium Widget",
                "quantity": "10",
                "price": "25.50",
                "tax_rate": "20"
            },
            {
                "product_code": "XYZ456",
                "description": "Deluxe Gadget",
                "quantity": "5",
                "price": "40.00",
                "tax_rate": "20"
            }
        ],
        "tax": {"rate": "20"},
        "payment_terms": {"due_date": "20250422"}
    }

if __name__ == "__main__":
    try:
        # Generate and print example invoice
        example_data = generate_example_invoic()
        edi_message = generate_invoic(
            example_data,
            filename="invoic_example.edi"
        )
        
        print("\nGenerated INVOIC Message:\n")
        print(edi_message)
        print("\nExample invoice saved to 'invoic_example.edi'")
    except EDIFACTGeneratorError as e:
        logger.error("Failed to generate INVOIC: %s", e)
