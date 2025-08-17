#!/usr/bin/env python3
import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional
import io
import os
import json
import argparse

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
    DEFAULT_DATE_FORMAT = "%Y%m%d"
    DEFAULT_FILE_ENCODING = "utf-8"
    
    # Validation constants
    MAX_PRODUCT_CODE_LENGTH = 35
    MAX_DESCRIPTION_LENGTH = 70
    VALID_PARTY_QUALIFIERS = {"BY", "SU", "IV", "DP", "PE"}
    VALID_PAYMENT_METHODS = {BANK_TRANSFER_PAYMENT, CREDIT_CARD_PAYMENT}
    VALID_CURRENCIES = {"USD", "EUR", "GBP"}  # Example currency codes

class EDIFACTGeneratorError(Exception):
    """Custom exception for EDIFACT generation errors"""
    pass

class EDIFACTValidator:
    """Handles validation of EDIFACT data"""
    
    @staticmethod
    def sanitize_value(value: Any, uppercase: bool = False) -> str:
        """Sanitize input value by stripping and optionally converting to uppercase."""
        result = str(value).strip()
        return result.upper() if uppercase else result
    
    @staticmethod
    def validate_date(date_str: str, date_format: str = EDIFACTConfig.DEFAULT_DATE_FORMAT) -> bool:
        """Validate date format with configurable format"""
        try:
            datetime.datetime.strptime(date_str.strip(), date_format)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def validate_decimal(value: Any) -> bool:
        """Validate decimal value"""
        try:
            Decimal(str(value).strip())
            return True
        except (InvalidOperation, TypeError):
            return False
    
    @staticmethod
    def validate_positive_number(value: Any) -> bool:
        """Validate positive number"""
        try:
            num = Decimal(str(value).strip())
            return num >= 0
        except (InvalidOperation, TypeError):
            return False
    
    @classmethod
    def validate_party(cls, party: Dict[str, str]) -> None:
        """Validate party information with sanitization"""
        if "qualifier" not in party or "id" not in party:
            raise EDIFACTGeneratorError("Each party must have 'qualifier' and 'id'")
        
        qualifier = cls.sanitize_value(party["qualifier"], uppercase=True)
        party_id = cls.sanitize_value(party["id"])
        
        if qualifier not in EDIFACTConfig.VALID_PARTY_QUALIFIERS:
            raise EDIFACTGeneratorError(
                f"Invalid party qualifier: {qualifier}. "
                f"Valid values are: {', '.join(EDIFACTConfig.VALID_PARTY_QUALIFIERS)}"
            )
        
        if not party_id:
            raise EDIFACTGeneratorError("Party ID must be a non-empty string")
    
    @classmethod
    def validate_item(cls, item: Dict[str, Any], index: int) -> None:
        """Validate an invoice item"""
        required_fields = ["product_code", "description", "quantity", "price"]
        for field in required_fields:
            if field not in item:
                raise EDIFACTGeneratorError(f"Item {index} missing required field: {field}")
        
        product_code = cls.sanitize_value(item["product_code"])
        description = cls.sanitize_value(item["description"])
        
        if len(product_code) > EDIFACTConfig.MAX_PRODUCT_CODE_LENGTH:
            raise EDIFACTGeneratorError(
                f"Item {index} product code exceeds maximum length of "
                f"{EDIFACTConfig.MAX_PRODUCT_CODE_LENGTH} characters"
            )
        
        if len(description) > EDIFACTConfig.MAX_DESCRIPTION_LENGTH:
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
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    @staticmethod
    def _escape_segment_value(value: str) -> str:
        """Escape EDIFACT special characters in segment values"""
        return value.replace("'", "?'").replace("+", "?+").replace(":", "?:")
    
    def generate_invoic(
        self,
        data: Dict[str, Any],
        filename: Optional[str] = None,
        edi_version: str = EDIFACTConfig.DEFAULT_EDI_VERSION,
        character_set: str = EDIFACTConfig.DEFAULT_CHARACTER_SET,
        date_format: str = EDIFACTConfig.DEFAULT_DATE_FORMAT,
        file_encoding: str = EDIFACTConfig.DEFAULT_FILE_ENCODING,
        force: bool = False
    ) -> str:
        """
        Generate an EDIFACT INVOIC message and optionally save to a file.
        
        Args:
            data: Dictionary containing invoice data
            filename: Optional filename to save the EDI message
            edi_version: EDI version syntax
            character_set: Character set identifier
            date_format: Date format for validation (default: YYYYMMDD)
            file_encoding: File encoding for saving (default: utf-8)
            force: Overwrite existing file if True
        
        Returns:
            Generated EDIFACT message as string
        """
        self._validate_invoice_data(data, date_format)
        self.logger.info("Generating INVOIC message for invoice %s", data["invoice_number"])
        
        # Use StringIO for efficient string building
        buffer = io.StringIO()
        
        # UNA: Service string advice (defines segment separators and escape characters)
        buffer.write("UNA:+.? '\n")
        self.logger.debug("Added segment: UNA")
        
        # UNH: Message header (specifies message type, version, and reference)
        buffer.write(f"UNH+{self._escape_segment_value(data['message_ref'])}"
                     f"+INVOIC:{edi_version}:{character_set}'\n")
        self.logger.debug("Added segment: UNH")
        
        # BGM: Beginning of message (specifies document type and invoice number)
        buffer.write(f"BGM+{EDIFACTConfig.INVOIC_DOCUMENT_TYPE}"
                     f"+{self._escape_segment_value(data['invoice_number'])}"
                     f"+{EDIFACTConfig.ORIGINAL_DOCUMENT}'\n")
        self.logger.debug("Added segment: BGM")
        
        # DTM: Date/time (specifies invoice issuance date)
        buffer.write(f"DTM+137:{data['invoice_date']}:102'\n")
        self.logger.debug("Added segment: DTM")
        
        # Add currency segment if specified
        if "currency" in data:
            buffer.write(f"CUX+2:{data['currency']}:9'\n")
            self.logger.debug("Added segment: CUX")
        
        # Add reference segment if specified
        if "reference" in data:
            buffer.write(f"RFF+ON:{self._escape_segment_value(data['reference'])}'\n")
            self.logger.debug("Added segment: RFF")
        
        # Add party segments
        for segment in self._generate_party_segments(data["parties"]):
            buffer.write(f"{segment}\n")
            self.logger.debug("Added segment: NAD")
        
        # Process items
        total_amount, total_tax = self._process_items(data["items"], buffer)
        
        # Add monetary totals
        for segment in self._generate_monetary_segments(total_amount, total_tax):
            buffer.write(f"{segment}\n")
            self.logger.debug("Added segment: MOA")
        
        # Add payment terms if available
        if "payment_terms" in data:
            for segment in self._generate_payment_segments(data["payment_terms"], date_format):
                buffer.write(f"{segment}\n")
                self.logger.debug("Added segment: %s", segment[:3])
        
        # UNT: Message trailer (specifies segment count and message reference)
        segment_count = len(buffer.getvalue().strip().split("\n"))
        buffer.write(f"UNT+{segment_count}+{self._escape_segment_value(data['message_ref'])}'\n")
        self.logger.debug("Added segment: UNT")
        
        # Get final message
        edifact_message = buffer.getvalue()
        
        # Validate ASCII for UNOA character set
        if character_set == "UNOA" and not edifact_message.isascii():
            self.logger.warning("Non-ASCII characters detected with UNOA character set")
        
        buffer.close()
        
        if filename:
            self._save_to_file(edifact_message, filename, file_encoding, force)
        
        return edifact_message
    
    def _validate_invoice_data(self, data: Dict[str, Any], date_format: str) -> None:
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
        
        if not EDIFACTValidator.validate_date(data["invoice_date"], date_format):
            raise EDIFACTGeneratorError(f"Invalid invoice_date format. Expected {date_format}")
        
        # Validate presence of required party qualifiers (BY and SU)
        required_qualifiers = {"BY", "SU"}
        if not all(any(EDIFACTValidator.sanitize_value(party["qualifier"], uppercase=True) == q 
                       for party in data["parties"]) for q in required_qualifiers):
            raise EDIFACTGeneratorError("Invoice must include both buyer (BY) and supplier (SU) parties")
        
        for party in data["parties"]:
            EDIFACTValidator.validate_party(party)
        
        if len(data["items"]) == 0:
            raise EDIFACTGeneratorError("INVOIC must contain at least one item")
        
        for index, item in enumerate(data["items"], start=1):
            EDIFACTValidator.validate_item(item, index)
        
        if "payment_terms" in data:
            if "due_date" in data["payment_terms"]:
                if not EDIFACTValidator.validate_date(data["payment_terms"]["due_date"], date_format):
                    raise EDIFACTGeneratorError(f"Invalid due_date format. Expected {date_format}")
            if "method" in data["payment_terms"]:
                method = EDIFACTValidator.sanitize_value(data["payment_terms"]["method"])
                if method not in EDIFACTConfig.VALID_PAYMENT_METHODS:
                    raise EDIFACTGeneratorError(
                        f"Invalid payment method: {method}. "
                        f"Valid values are: {', '.join(EDIFACTConfig.VALID_PAYMENT_METHODS)}"
                    )
        
        if "currency" in data:
            currency = EDIFACTValidator.sanitize_value(data["currency"], uppercase=True)
            if currency not in EDIFACTConfig.VALID_CURRENCIES:
                raise EDIFACTGeneratorError(
                    f"Invalid currency: {currency}. "
                    f"Valid values are: {', '.join(EDIFACTConfig.VALID_CURRENCIES)}"
                )
        
        if "reference" in data:
            reference = EDIFACTValidator.sanitize_value(data["reference"])
            if not reference:
                raise EDIFACTGeneratorError("Reference cannot be empty")
    
    def _generate_party_segments(self, parties: List[Dict[str, str]]) -> List[str]:
        """Generate NAD segments for all parties (name and address)"""
        return [
            f"NAD+{EDIFACTValidator.sanitize_value(party['qualifier'], uppercase=True)}+"
            f"{self._escape_segment_value(EDIFACTValidator.sanitize_value(party['id']))}::91'"
            for party in parties
        ]
    
    def _process_items(
        self,
        items: List[Dict[str, Any]],
        buffer: io.StringIO
    ) -> tuple[Decimal, Decimal]:
        """Process all items and add segments, returning totals"""
        total_amount = Decimal("0.00")
        total_tax = Decimal("0.00")
        
        for index, item in enumerate(items, start=1):
            quantity = Decimal(EDIFACTValidator.sanitize_value(item["quantity"]))
            price = Decimal(EDIFACTValidator.sanitize_value(item["price"]))
            tax_rate = Decimal(EDIFACTValidator.sanitize_value(item.get("tax_rate", "0")))
            
            line_total = price * quantity
            total_amount += line_total
            
            # LIN: Line item (specifies item number and product code)
            buffer.write(f"LIN+{index}++{self._escape_segment_value(EDIFACTValidator.sanitize_value(item['product_code']))}:EN'\n")
            self.logger.debug("Added segment: LIN for item %d", index)
            
            # IMD: Item description (provides item description)
            buffer.write(f"IMD+F++:::{self._escape_segment_value(EDIFACTValidator.sanitize_value(item['description']))}'\n")
            self.logger.debug("Added segment: IMD for item %d", index)
            
            # QTY: Quantity (specifies item quantity)
            buffer.write(f"QTY+47:{quantity}:EA'\n")
            self.logger.debug("Added segment: QTY for item %d", index)
            
            # PRI: Price (specifies unit price)
            buffer.write(f"PRI+AAA:{price:.2f}:EA'\n")
            self.logger.debug("Added segment: PRI for item %d", index)
            
            # Add tax segments if applicable
            if tax_rate > 0:
                tax_value = (line_total * tax_rate) / Decimal("100")
                total_tax += tax_value
                # TAX: Tax details (specifies tax type and rate)
                buffer.write(f"TAX+7+{EDIFACTConfig.VAT_TAX_CATEGORY}+++{tax_rate:.2f}+S'\n")
                self.logger.debug("Added segment: TAX for item %d", index)
                # MOA: Monetary amount (specifies tax amount for item)
                buffer.write(f"MOA+125:{tax_value:.2f}:'\n")
                self.logger.debug("Added segment: MOA for item %d (tax)", index)
        
        return total_amount, total_tax
    
    def _generate_monetary_segments(
        self,
        total_amount: Decimal,
        total_tax: Decimal
    ) -> List[str]:
        """Generate MOA segments for monetary totals"""
        grand_total = total_amount + total_tax
        segments = [
            f"MOA+86:{total_amount:.2f}:'",  # Total before tax
            f"MOA+176:{total_tax:.2f}:'",    # Total tax
            f"MOA+9:{grand_total:.2f}:'"      # Invoice total
        ]
        return segments
    
    def _generate_payment_segments(self, payment_terms: Dict[str, Any], date_format: str) -> List[str]:
        """Generate PAT and DTM segments for payment terms"""
        segments = []
        if "due_date" in payment_terms:
            payment_method = EDIFACTValidator.sanitize_value(
                payment_terms.get("method", EDIFACTConfig.BANK_TRANSFER_PAYMENT))
            segments.extend([
                f"PAT+1++{payment_method}'",
                f"DTM+13:{payment_terms['due_date']}:102'"
            ])
        return segments
    
    def _save_to_file(self, content: str, filename: str, encoding: str, force: bool = False) -> None:
        """Save the EDI message to a file with specified encoding"""
        if not force and os.path.exists(filename):
            raise EDIFACTGeneratorError(f"File {filename} exists. Use --force to overwrite.")
        try:
            with open(filename, "w", encoding=encoding) as f:
                f.write(content)
            self.logger.info("INVOIC message saved to %s with encoding %s", filename, encoding)
        except OSError as e:
            self.logger.error("Failed to write file %s: %s", filename, e)
            raise EDIFACTGeneratorError(f"File write error: {e}") from e

def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure application logging with customizable level"""
    logger = logging.getLogger(__name__)
    if not logger.handlers:  # Avoid duplicate handlers
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(level)
    return logger

def generate_example_invoic() -> Dict[str, Any]:
    """Generate example INVOIC data for testing"""
    return {
        "message_ref": "789123",
        "invoice_number": "INV2025001",
        "invoice_date": "20250322",
        "currency": "EUR",
        "reference": "PO12345",  # Added example reference
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
    logger = configure_logging(logging.DEBUG)  # Set to DEBUG for detailed logging
    
    parser = argparse.ArgumentParser(description="Generate EDIFACT INVOIC messages")
    parser.add_argument("--input", help="JSON file with invoice data")
    parser.add_argument("--output", default="invoic.edi", help="Output EDI file (default: invoic.edi)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args()
    
    try:
        if args.input:
            with open(args.input, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Loaded invoice data from %s", args.input)
        else:
            data = generate_example_invoic()
            logger.info("Using example invoice data")
        
        generator = EDIFACTGenerator(logger=logger)
        edi_message = generator.generate_invoic(
            data,
            filename=args.output,
            force=args.force
        )
        
        print("\nGenerated INVOIC Message:\n")
        print(edi_message)
        print(f"\nInvoice saved to '{args.output}'")
    except (EDIFACTGeneratorError, OSError, json.JSONDecodeError) as e:
        logger.error("Failed to generate INVOIC: %s", e)
        exit(1)
