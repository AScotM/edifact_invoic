import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def validate_data(data):
    """Validate required fields in INVOIC data."""
    required_fields = ["message_ref", "invoice_number", "invoice_date", "parties", "items", "tax", "payment_terms"]
    for field in required_fields:
        if field not in data or not data[field]:
            raise ValueError(f"Missing required field: {field}")
    if not isinstance(data["items"], list) or len(data["items"]) == 0:
        raise ValueError("INVOIC must contain at least one item.")
    logging.info("Data validation passed.")

def generate_invoic(data, filename="invoic.edi"):
    """Generate an EDIFACT INVOIC message and save to a file."""
    try:
        validate_data(data)
    except ValueError as e:
        logging.error(e)
        return ""

    logging.info("Generating INVOIC message...")
    
    edifact = [
        "UNA:+.? '",  # Service string advice
        f"UNH+{data['message_ref']}+INVOIC:D:96A:UN'"
    ]
    
    edifact.append(f"BGM+380+{data['invoice_number']}+9'")  # 380 = Invoice
    edifact.append(f"DTM+137:{data['invoice_date']}:102'")
    
    for party in data['parties']:
        if "qualifier" not in party or "id" not in party:
            logging.warning("Skipping invalid NAD entry: %s", party)
            continue
        edifact.append(f"NAD+{party['qualifier']}+{party['id']}::91'")
    
    total_amount = 0.0
    total_tax = 0.0
    
    for index, item in enumerate(data['items'], start=1):
        if "product_code" not in item or "description" not in item or "quantity" not in item or "price" not in item:
            logging.warning("Skipping item due to missing fields: %s", item)
            continue
        edifact.append(f"LIN+{index}++{item['product_code']}:EN'")
        edifact.append(f"IMD+F++:::{item['description']}'")
        edifact.append(f"QTY+47:{item['quantity']}:EA'")
        edifact.append(f"PRI+AAA:{item['price']}:EA'")
        line_total = float(item['price']) * int(item['quantity'])
        total_amount += line_total
        
        if "tax_rate" in item:
            tax_value = line_total * (float(item['tax_rate']) / 100)
            total_tax += tax_value
            edifact.append(f"TAX+7+VAT+++{item['tax_rate']}+S'")
            edifact.append(f"MOA+125:{tax_value:.2f}:'")
    
    grand_total = total_amount + total_tax
    edifact.append(f"MOA+86:{total_amount:.2f}:'")  # Total before tax
    edifact.append(f"MOA+176:{total_tax:.2f}:'")  # Tax amount
    edifact.append(f"MOA+9:{grand_total:.2f}:'")  # Invoice total
    
    if "payment_terms" in data:
        edifact.append(f"PAT+1++5'" )  # 5 = Bank Transfer
        edifact.append(f"DTM+13:{data['payment_terms']['due_date']}:102'")
    
    segment_count = len(edifact) - 1
    edifact.append(f"UNT+{segment_count}+{data['message_ref']}'")
    
    edifact_message = "\n".join(edifact)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(edifact_message)
    
    logging.info("INVOIC message generated and saved to %s", filename)
    return edifact_message

# Example data
invoic_data = {
    "message_ref": "789123",
    "invoice_number": "INV2025001",
    "invoice_date": "20250322",
    "parties": [
        {"qualifier": "BY", "id": "123456789"},
        {"qualifier": "SU", "id": "987654321"},
        {"qualifier": "IV", "id": "555555555"}  # Invoicee
    ],
    "items": [
        {"product_code": "ABC123", "description": "Product A", "quantity": "10", "price": "25.50", "tax_rate": "20"},
        {"product_code": "XYZ456", "description": "Product B", "quantity": "5", "price": "40.00", "tax_rate": "20"}
    ],
    "tax": {"rate": "20"},
    "payment_terms": {"due_date": "20250422"}
}

# Generate and save INVOIC
invoic_message = generate_invoic(invoic_data)
if invoic_message:
    print("\nGenerated INVOIC Message:\n")
    print(invoic_message)

