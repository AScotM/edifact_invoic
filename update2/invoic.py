import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional

class EDIFACTConfig:
    """Configuration for EDIFACT generation"""
    # Document types
    INVOIC_DOCUMENT_TYPE = "380"
    ORIGINAL_DOCUMENT = "9"
    
    # Tax categories
    VAT_TAX_CATEGORY = "VAT"
    SALES_TAX_CATEGORY = "SAL"
    
    # Payment methods
    BANK_TRANSFER_PAYMENT = "5"
    CREDIT_CARD_PAYMENT = "1"
    
    # Default values
    DEFAULT_EDI_VERSION = "D:96A:UN"
    DEFAULT_CHARACTER_SET = "UNOA"
    
    # Validation constants
    MAX_PRODUCT_CODE_LENGTH = 35
    MAX_DESCRIPTION_LENGTH = 70
    VALID_PARTY_QUALIFIERS = {"BY", "SU", "IV", "DP", "PE"}

class EDIFACTGeneratorError(Exception):
    """Custom exception for EDIFACT generation errors"""
    pass

class EDIFACTValidator:
    """Handles validation of EDIFACT data"""
    
    @staticmethod
    def validate_date(date_str: str, date_format: str = "%Y%m%d") -> bool:
        """Validate date format"""
        try:
            datetime.datetime.strptime(date_str, date_format)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def validate_decimal(value: Any) -> bool:
        """Validate decimal value"""
        try:
            Decimal(str(value))
            return True
        except (InvalidOperation, TypeError):
            return False
    
    @staticmethod
    def validate_positive_number(value: Any) -> bool:
        """Validate positive number"""
        try:
            num = Decimal(str(value))
            return num >= 0
        except (InvalidOperation, TypeError):
            return False
    
    @classmethod
    def validate_party(cls, party: Dict[str, str]) -> None:
        """Validate party information"""
        if "qualifier" not in party or "id" not in party:
            raise EDIFACTGeneratorError("Each party must have 'qualifier' and 'id'")
        
        if party["qualifier"] not in EDIFACTConfig.VALID_PARTY_QUALIFIERS:
            raise EDIFACTGeneratorError(
                f"Invalid party qualifier: {party['qualifier']}. "
                f"Valid values are: {', '.join(EDIFACTConfig.VALID_PARTY_QUALIFIERS)}"
            )
        
        if not isinstance(party["id"], str) or not party["id"].strip():
            raise EDIFACTGeneratorError("Party ID must be a non-empty string")
    
    @classmethod
    def validate_item(cls, item: Dict[str, Any], index: int) -> None:
        """Validate an invoice item"""
        required_fields = ["product_code", "description", "quantity", "price"]
        for field in required_fields:
            if field not in item:
                raise EDIFACTGeneratorError(f"Item {index} missing required field: {field}")
        
        if len(item["product_code"]) > EDIFACTConfig.MAX_PRODUCT_CODE_LENGTH:
            raise EDIFACTGeneratorError(
                f"Item {index} product code exceeds maximum length of "
                f"{EDIFACTConfig.MAX_PRODUCT_CODE_LENGTH} characters"
            )
        
        if len(item["description"]) > EDIFACTConfig.MAX_DESCRIPTION_LENGTH:
            raise EDIFACTGeneratorError(
                f"Item {index} description exceeds maximum length of "
                f"{EDIFACTConfig.MAX_DESCRIPTION_LENGTH} characters"
            )
        
        if not cls.validate_positive_number(item["quantity"]):
            raise EDIFACTGeneratorError(f"Item {index} has invalid quantity: {item['quantity']}")
        
        if not cls.validate_positive_number(item["price"]):
            raise EDIFACTGeneratorError(f"Item {index} has invalid price: {item['price']}")
        
        if "tax_rate" in item and not cls.validate_positive_number(item["tax_rate"]):
            raise EDIFACTGeneratorError(f"Item {index} has invalid tax_rate: {item['tax_rate']}")

class EDIFACTGenerator:
    """Generates EDIFACT INVOIC messages"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def generate_invoic(
        self,
        data: Dict[str, Any],
        filename: Optional[str] = None,
        edi_version: str = EDIFACTConfig.DEFAULT_EDI_VERSION,
        character_set: str = EDIFACTConfig.DEFAULT_CHARACTER_SET
    ) -> str:
        """
        Generate an EDIFACT INVOIC message and optionally save to a file.
        
        Args:
            data: Dictionary containing invoice data
            filename: Optional filename to save the EDI message
            edi_version: EDI version syntax
            character_set: Character set identifier
        
        Returns:
            Generated EDIFACT message as string
        """
        self._validate_invoice_data(data)
        self.logger.info("Generating INVOIC message...")
        
        segments = [
            f"UNA:+.? '",  # Service string advice
            f"UNH+{data['message_ref']}+INVOIC:{edi_version}:{character_set}'",
            f"BGM+{EDIFACTConfig.INVOIC_DOCUMENT_TYPE}+{data['invoice_number']}+{EDIFACTConfig.ORIGINAL_DOCUMENT}'",
            f"DTM+137:{data['invoice_date']}:102'"
        ]
        
        # Add parties
        segments.extend(self._generate_party_segments(data["parties"]))
        
        # Process items
        total_amount, total_tax = self._process_items(data["items"], segments)
        
        # Add monetary totals
        segments.extend(self._generate_monetary_segments(total_amount, total_tax))
        
        # Add payment terms if available
        if "payment_terms" in data:
            segments.extend(self._generate_payment_segments(data["payment_terms"]))
        
        # Add message trailer
        segment_count = len(segments) - 1  # Exclude UNA segment
        segments.append(f"UNT+{segment_count}+{data['message_ref']}'")
        
        # Combine and optionally save
        edifact_message = "\n".join(segments)
        
        if filename:
            self._save_to_file(edifact_message, filename)
        
        return edifact_message
    
    def _validate_invoice_data(self, data: Dict[str, Any]) -> None:
        """Validate the complete invoice data structure"""
        required_fields = {
            "message_ref": str,
            "invoice_number": str,
            "invoice_date": str,
            "parties": list,
            "items": list
        }
        
        for field, field_type in required_fields.items():
            if field not in data:
                raise EDIFACTGeneratorError(f"Missing required field: {field}")
            if not isinstance(data[field], field_type):
                raise EDIFACTGeneratorError(f"Field {field} must be {field_type.__name__}")
            if not data[field]:  # Check not empty
                raise EDIFACTGeneratorError(f"Field {field} cannot be empty")
        
        if not EDIFACTValidator.validate_date(data["invoice_date"]):
            raise EDIFACTGeneratorError("Invalid invoice_date format. Expected YYYYMMDD")
        
        for party in data["parties"]:
            EDIFACTValidator.validate_party(party)
        
        if len(data["items"]) == 0:
            raise EDIFACTGeneratorError("INVOIC must contain at least one item")
        
        for index, item in enumerate(data["items"], start=1):
            EDIFACTValidator.validate_item(item, index)
        
        if "payment_terms" in data and "due_date" in data["payment_terms"]:
            if not EDIFACTValidator.validate_date(data["payment_terms"]["due_date"]):
                raise EDIFACTGeneratorError("Invalid due_date format. Expected YYYYMMDD")
    
    def _generate_party_segments(self, parties: List[Dict[str, str]]) -> List[str]:
        """Generate NAD segments for all parties"""
        return [f"NAD+{party['qualifier']}+{party['id']}::91'" for party in parties]
    
    def _process_items(
        self,
        items: List[Dict[str, Any]],
        segments: List[str]
    ) -> tuple[Decimal, Decimal]:
        """Process all items and add segments, returning totals"""
        total_amount = Decimal("0.00")
        total_tax = Decimal("0.00")
        
        for index, item in enumerate(items, start=1):
            quantity = Decimal(str(item["quantity"]))
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
                    f"TAX+7+{EDIFACTConfig.VAT_TAX_CATEGORY}+++{tax_rate:.2f}+S'",
                    f"MOA+125:{tax_value:.2f}:'"
                ])
        
        return total_amount, total_tax
    
    def _generate_monetary_segments(
        self,
        total_amount: Decimal,
        total_tax: Decimal
    ) -> List[str]:
        """Generate monetary total segments"""
        grand_total = total_amount + total_tax
        return [
            f"MOA+86:{total_amount:.2f}:'",  # Total before tax
            f"MOA+176:{total_tax:.2f}:'",    # Total tax
            f"MOA+9:{grand_total:.2f}:'"      # Invoice total
        ]
    
    def _generate_payment_segments(self, payment_terms: Dict[str, Any]) -> List[str]:
        """Generate payment-related segments"""
        segments = []
        if "due_date" in payment_terms:
            payment_method = payment_terms.get("method", EDIFACTConfig.BANK_TRANSFER_PAYMENT)
            segments.extend([
                f"PAT+1++{payment_method}'",
                f"DTM+13:{payment_terms['due_date']}:102'"
            ])
        return segments
    
    def _save_to_file(self, content: str, filename: str) -> None:
        """Save the EDI message to a file"""
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            self.logger.info("INVOIC message saved to %s", filename)
        except OSError as e:
            self.logger.error("Failed to write file %s: %s", filename, e)
            raise EDIFACTGeneratorError(f"File write error: {e}") from e

def configure_logging() -> None:
    """Configure application logging"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

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
        "payment_terms": {
            "due_date": "20250422",
            "method": "5"  # Bank transfer
        }
    }

if __name__ == "__main__":
    configure_logging()
    logger = logging.getLogger(__name__)
    
    try:
        generator = EDIFACTGenerator()
        example_data = generate_example_invoic()
        
        edi_message = generator.generate_invoic(
            example_data,
            filename="invoic_example.edi"
        )
        
        print("\nGenerated INVOIC Message:\n")
        print(edi_message)
        print("\nExample invoice saved to 'invoic_example.edi'")
    except EDIFACTGeneratorError as e:
        logger.error("Failed to generate INVOIC: %s", e)
