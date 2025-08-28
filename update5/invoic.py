#!/usr/bin/env python3
"""
EDIFACT INVOIC Generator
A comprehensive implementation for generating EDIFACT INVOIC messages.
"""

import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional, Tuple
import io
import os
import json
import argparse
import re

class EDIFACTConfig:
    """Configuration for EDIFACT generation with enhanced flexibility"""
    
    # Default separators and terminators (EDIFACT standard)
    DEFAULT_DATA_SEPARATOR = "+"
    DEFAULT_COMPONENT_SEPARATOR = ":"
    DEFAULT_SEGMENT_TERMINATOR = "'"
    DEFAULT_DECIMAL_NOTATION = "."
    
    # Document types
    INVOIC_DOCUMENT_TYPE = "380"
    ORIGINAL_DOCUMENT = "9"
    
    # Tax categories
    VAT_TAX_CATEGORY = "VAT"
    SALES_TAX_CATEGORY = "SAL"
    
    # Payment methods
    BANK_TRANSFER_PAYMENT = "5"
    CREDIT_CARD_PAYMENT = "1"
    CASH_PAYMENT = "10"
    
    # Default values
    DEFAULT_EDI_VERSION = "D:96A:UN"
    DEFAULT_CHARACTER_SET = "UNOA"
    DEFAULT_DATE_FORMAT = "%Y%m%d"
    DEFAULT_FILE_ENCODING = "utf-8"
    DEFAULT_MESSAGE_REF_PREFIX = "INV"
    
    # Validation constants
    MAX_PRODUCT_CODE_LENGTH = 35
    MAX_DESCRIPTION_LENGTH = 70
    MAX_NAME_LENGTH = 35
    MAX_ADDRESS_LINE_LENGTH = 35
    MAX_CITY_LENGTH = 35
    MAX_COUNTRY_LENGTH = 3
    
    VALID_PARTY_QUALIFIERS = {"BY", "SU", "IV", "DP", "PE"}
    VALID_PAYMENT_METHODS = {BANK_TRANSFER_PAYMENT, CREDIT_CARD_PAYMENT, CASH_PAYMENT}
    VALID_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY"}  # Expanded currency codes
    VALID_COUNTRIES = {"US", "GB", "FR", "DE", "IT", "ES", "NL", "BE", "CN", "JP", "AU", "CA"}  # Common countries
    
    # Segment identifiers
    SEGMENT_UNA = "UNA"
    SEGMENT_UNB = "UNB"
    SEGMENT_UNH = "UNH"
    SEGMENT_BGM = "BGM"
    SEGMENT_DTM = "DTM"
    SEGMENT_NAD = "NAD"
    SEGMENT_CUX = "CUX"
    SEGMENT_RFF = "RFF"
    SEGMENT_LIN = "LIN"
    SEGMENT_IMD = "IMD"
    SEGMENT_QTY = "QTY"
    SEGMENT_PRI = "PRI"
    SEGMENT_TAX = "TAX"
    SEGMENT_MOA = "MOA"
    SEGMENT_PAT = "PAT"
    SEGMENT_UNT = "UNT"
    SEGMENT_UNZ = "UNZ"

class EDIFACTGeneratorError(Exception):
    """Custom exception for EDIFACT generation errors"""
    pass

class EDIFACTValidator:
    """Handles validation of EDIFACT data with enhanced validation"""
    
    @staticmethod
    def sanitize_value(value: Any, uppercase: bool = False, max_length: Optional[int] = None) -> str:
        """Sanitize input value by stripping and optionally converting to uppercase."""
        if value is None:
            return ""
            
        result = str(value).strip()
        if uppercase:
            result = result.upper()
            
        if max_length and len(result) > max_length:
            result = result[:max_length]
            
        return result
    
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
    
    @staticmethod
    def validate_alphanumeric(value: str, field_name: str) -> None:
        """Validate that value contains only alphanumeric characters and allowed symbols"""
        if not re.match(r'^[a-zA-Z0-9\s_\-\.\@\#\&]+$', value):
            raise EDIFACTGeneratorError(f"Invalid characters in {field_name}: {value}")
    
    @classmethod
    def validate_party(cls, party: Dict[str, str]) -> None:
        """Validate party information with enhanced validation"""
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
        
        # Validate name if provided
        if "name" in party:
            name = cls.sanitize_value(party["name"], max_length=EDIFACTConfig.MAX_NAME_LENGTH)
            cls.validate_alphanumeric(name, "party name")
        
        # Validate country if provided
        if "country" in party:
            country = cls.sanitize_value(party["country"], uppercase=True)
            if country not in EDIFACTConfig.VALID_COUNTRIES:
                raise EDIFACTGeneratorError(
                    f"Invalid country code: {country}. "
                    f"Valid values are: {', '.join(EDIFACTConfig.VALID_COUNTRIES)}"
                )
    
    @classmethod
    def validate_item(cls, item: Dict[str, Any], index: int) -> None:
        """Validate an invoice item with enhanced validation"""
        required_fields = ["product_code", "description", "quantity", "price"]
        for field in required_fields:
            if field not in item:
                raise EDIFACTGeneratorError(f"Item {index} missing required field: {field}")
        
        product_code = cls.sanitize_value(item["product_code"])
        description = cls.sanitize_value(item["description"])
        
        cls.validate_alphanumeric(product_code, "product code")
        cls.validate_alphanumeric(description, "description")
        
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
        
        # Validate unit of measure if provided
        if "unit" in item:
            unit = cls.sanitize_value(item["unit"], uppercase=True)
            cls.validate_alphanumeric(unit, "unit")

class EDIFACTGenerator:
    """Generates EDIFACT INVOIC messages with enhanced functionality"""
    
    def __init__(
        self, 
        logger: Optional[logging.Logger] = None,
        data_separator: str = EDIFACTConfig.DEFAULT_DATA_SEPARATOR,
        component_separator: str = EDIFACTConfig.DEFAULT_COMPONENT_SEPARATOR,
        segment_terminator: str = EDIFACTConfig.DEFAULT_SEGMENT_TERMINATOR,
        decimal_notation: str = EDIFACTConfig.DEFAULT_DECIMAL_NOTATION
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.data_separator = data_separator
        self.component_separator = component_separator
        self.segment_terminator = segment_terminator
        self.decimal_notation = decimal_notation
    
    def _escape_segment_value(self, value: str) -> str:
        """Escape EDIFACT special characters in segment values"""
        # Escape the escape character first
        value = value.replace("?", "??")
        # Escape other special characters
        value = value.replace("'", "?'")
        value = value.replace(self.data_separator, f"?{self.data_separator}")
        value = value.replace(self.component_separator, f"?{self.component_separator}")
        value = value.replace(" ", "? ")
        return value
    
    def _build_segment(self, segment_id: str, *elements: str) -> str:
        """Build an EDIFACT segment with proper formatting"""
        segment_elements = self.data_separator.join(elements)
        return f"{segment_id}{self.data_separator}{segment_elements}{self.segment_terminator}"
    
    def generate_invoic(
        self,
        data: Dict[str, Any],
        filename: Optional[str] = None,
        edi_version: str = EDIFACTConfig.DEFAULT_EDI_VERSION,
        character_set: str = EDIFACTConfig.DEFAULT_CHARACTER_SET,
        date_format: str = EDIFACTConfig.DEFAULT_DATE_FORMAT,
        file_encoding: str = EDIFACTConfig.DEFAULT_FILE_ENCODING,
        force: bool = False,
        interchange_control_ref: Optional[str] = None,
        application_ref: Optional[str] = None
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
            interchange_control_ref: Interchange control reference for UNB/UNZ
            application_ref: Application reference for UNB
        
        Returns:
            Generated EDIFACT message as string
        """
        self._validate_invoice_data(data, date_format)
        self.logger.info("Generating INVOIC message for invoice %s", data["invoice_number"])
        
        # Use StringIO for efficient string building
        buffer = io.StringIO()
        segment_count = 0
        
        # Generate interchange header (UNB)
        unb_segment = self._generate_interchange_header(
            data, 
            interchange_control_ref, 
            application_ref, 
            character_set
        )
        buffer.write(f"{unb_segment}\n")
        segment_count += 1
        self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_UNB)
        
        # Generate message header (UNH)
        unh_segment = self._generate_message_header(data, edi_version, character_set)
        buffer.write(f"{unh_segment}\n")
        segment_count += 1
        self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_UNH)
        
        # BGM: Beginning of message (specifies document type and invoice number)
        bgm_segment = self._build_segment(
            EDIFACTConfig.SEGMENT_BGM,
            EDIFACTConfig.INVOIC_DOCUMENT_TYPE,
            self._escape_segment_value(EDIFACTValidator.sanitize_value(data["invoice_number"])),
            EDIFACTConfig.ORIGINAL_DOCUMENT
        )
        buffer.write(f"{bgm_segment}\n")
        segment_count += 1
        self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_BGM)
        
        # DTM: Date/time (specifies invoice issuance date)
        dtm_segment = self._build_segment(
            EDIFACTConfig.SEGMENT_DTM,
            f"137{self.component_separator}{data['invoice_date']}{self.component_separator}102"
        )
        buffer.write(f"{dtm_segment}\n")
        segment_count += 1
        self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_DTM)
        
        # Add currency segment if specified
        if "currency" in data:
            cux_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_CUX,
                f"2{self.component_separator}{data['currency']}{self.component_separator}9"
            )
            buffer.write(f"{cux_segment}\n")
            segment_count += 1
            self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_CUX)
        
        # Add reference segment if specified
        if "reference" in data:
            rff_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_RFF,
                f"ON{self.component_separator}{self._escape_segment_value(EDIFACTValidator.sanitize_value(data['reference']))}"
            )
            buffer.write(f"{rff_segment}\n")
            segment_count += 1
            self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_RFF)
        
        # Add party segments
        for segment in self._generate_party_segments(data["parties"]):
            buffer.write(f"{segment}\n")
            segment_count += 1
            self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_NAD)
        
        # Process items
        total_amount, total_tax, item_segments = self._process_items(data["items"])
        for segment in item_segments:
            buffer.write(f"{segment}\n")
            segment_count += 1
        
        # Add monetary totals
        for segment in self._generate_monetary_segments(total_amount, total_tax):
            buffer.write(f"{segment}\n")
            segment_count += 1
            self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_MOA)
        
        # Add payment terms if available
        if "payment_terms" in data:
            for segment in self._generate_payment_segments(data["payment_terms"], date_format):
                buffer.write(f"{segment}\n")
                segment_count += 1
                self.logger.debug("Added segment: %s", segment[:3])
        
        # UNT: Message trailer (specifies segment count and message reference)
        # Note: +2 accounts for UNB and UNZ segments that wrap the message
        unt_segment = self._build_segment(
            EDIFACTConfig.SEGMENT_UNT,
            str(segment_count + 2),  # +2 for UNB and UNZ
            self._escape_segment_value(EDIFACTValidator.sanitize_value(data["message_ref"]))
        )
        buffer.write(f"{unt_segment}\n")
        segment_count += 1
        self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_UNT)
        
        # UNZ: Interchange trailer
        unz_segment = self._build_segment(
            EDIFACTConfig.SEGMENT_UNZ,
            "1",  # Number of messages in interchange
            interchange_control_ref or EDIFACTValidator.sanitize_value(data["message_ref"])
        )
        buffer.write(f"{unz_segment}\n")
        segment_count += 1
        self.logger.debug("Added segment: %s", EDIFACTConfig.SEGMENT_UNZ)
        
        # Get final message
        edifact_message = buffer.getvalue()
        
        # Validate ASCII for UNOA character set
        if character_set == "UNOA" and not edifact_message.isascii():
            self.logger.warning("Non-ASCII characters detected with UNOA character set")
        
        buffer.close()
        
        if filename:
            self._save_to_file(edifact_message, filename, file_encoding, force)
        
        return edifact_message
    
    def _generate_interchange_header(
        self, 
        data: Dict[str, Any],
        interchange_control_ref: Optional[str],
        application_ref: Optional[str],
        character_set: str
    ) -> str:
        """Generate UNB segment for interchange header"""
        # Generate timestamp in format YYMMDD:HHMM
        now = datetime.datetime.now()
        timestamp = now.strftime("%y%m%d:%H%M")
        
        # Use provided references or generate defaults
        control_ref = interchange_control_ref or EDIFACTValidator.sanitize_value(data["message_ref"])
        app_ref = application_ref or "PYEDIFACT"
        
        return self._build_segment(
            EDIFACTConfig.SEGMENT_UNB,
            f"UNOC{self.component_separator}3",  # Syntax identifier and version
            f"{app_ref}{self.component_separator}{control_ref}",  # Sender
            f"RECEIVER{self.component_separator}001",  # Receiver (generic)
            f"{timestamp}",  # Date and time of preparation
            control_ref,  # Interchange control reference
            f"1{self.component_separator}{character_set}"  # Application password and character set
        )
    
    def _generate_message_header(
        self, 
        data: Dict[str, Any],
        edi_version: str,
        character_set: str
    ) -> str:
        """Generate UNH segment for message header"""
        return self._build_segment(
            EDIFACTConfig.SEGMENT_UNH,
            f"{self._escape_segment_value(EDIFACTValidator.sanitize_value(data['message_ref']))}",
            f"INVOIC{self.component_separator}{edi_version}{self.component_separator}{character_set}"
        )
    
    def _validate_invoice_data(self, data: Dict[str, Any], date_format: str) -> None:
        """Validate the complete invoice data structure with enhanced validation"""
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
        
        # Validate message reference format
        message_ref = EDIFACTValidator.sanitize_value(data["message_ref"])
        EDIFACTValidator.validate_alphanumeric(message_ref, "message reference")
        
        if not EDIFACTValidator.validate_date(data["invoice_date"], date_format):
            raise EDIFACTGeneratorError(f"Invalid invoice_date format. Expected {date_format}")
        
        # Validate presence of required party qualifiers (BY and SU)
        required_qualifiers = {"BY", "SU"}
        party_qualifiers = {
            EDIFACTValidator.sanitize_value(party["qualifier"], uppercase=True) 
            for party in data["parties"]
        }
        
        missing_qualifiers = required_qualifiers - party_qualifiers
        if missing_qualifiers:
            raise EDIFACTGeneratorError(
                f"Missing required party qualifiers: {', '.join(missing_qualifiers)}"
            )
        
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
            EDIFACTValidator.validate_alphanumeric(reference, "reference")
    
    def _generate_party_segments(self, parties: List[Dict[str, str]]) -> List[str]:
        """Generate NAD segments for all parties with enhanced information"""
        segments = []
        
        for party in parties:
            qualifier = EDIFACTValidator.sanitize_value(party["qualifier"], uppercase=True)
            party_id = self._escape_segment_value(EDIFACTValidator.sanitize_value(party["id"]))
            
            # Build basic NAD segment
            elements = [qualifier, party_id, "91"]  # 91 = Assigned by buyer or buyer's agent
            
            # Add name if available
            if "name" in party:
                name = self._escape_segment_value(
                    EDIFACTValidator.sanitize_value(
                        party["name"], 
                        max_length=EDIFACTConfig.MAX_NAME_LENGTH
                    )
                )
                elements.append(name)
            else:
                elements.append("")  # Empty component for name
            
            # Add address components if available
            address_elements = []
            if "street" in party:
                street = self._escape_segment_value(
                    EDIFACTValidator.sanitize_value(
                        party["street"], 
                        max_length=EDIFACTConfig.MAX_ADDRESS_LINE_LENGTH
                    )
                )
                address_elements.append(street)
            
            if "city" in party:
                city = self._escape_segment_value(
                    EDIFACTValidator.sanitize_value(
                        party["city"], 
                        max_length=EDIFACTConfig.MAX_CITY_LENGTH
                    )
                )
                address_elements.append(city)
            
            if "country" in party:
                country = EDIFACTValidator.sanitize_value(
                    party["country"], 
                    uppercase=True,
                    max_length=EDIFACTConfig.MAX_COUNTRY_LENGTH
                )
                address_elements.append(country)
            
            if address_elements:
                elements.append(self.component_separator.join(address_elements))
            
            segments.append(self._build_segment(EDIFACTConfig.SEGMENT_NAD, *elements))
        
        return segments
    
    def _process_items(
        self,
        items: List[Dict[str, Any]]
    ) -> Tuple[Decimal, Decimal, List[str]]:
        """Process all items and generate segments, returning totals and segments"""
        total_amount = Decimal("0.00")
        total_tax = Decimal("0.00")
        segments = []
        
        for index, item in enumerate(items, start=1):
            quantity = Decimal(EDIFACTValidator.sanitize_value(item["quantity"]))
            price = Decimal(EDIFACTValidator.sanitize_value(item["price"]))
            tax_rate = Decimal(EDIFACTValidator.sanitize_value(item.get("tax_rate", "0")))
            unit = EDIFACTValidator.sanitize_value(item.get("unit", "EA"), uppercase=True)
            
            line_total = price * quantity
            total_amount += line_total
            
            # LIN: Line item (specifies item number and product code)
            lin_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_LIN,
                str(index),
                "",
                f"{self._escape_segment_value(EDIFACTValidator.sanitize_value(item['product_code']))}{self.component_separator}EN"
            )
            segments.append(lin_segment)
            self.logger.debug("Added segment: LIN for item %d", index)
            
            # IMD: Item description (provides item description)
            imd_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_IMD,
                "F",
                "",
                "",
                "",
                self._escape_segment_value(EDIFACTValidator.sanitize_value(item["description"]))
            )
            segments.append(imd_segment)
            self.logger.debug("Added segment: IMD for item %d", index)
            
            # QTY: Quantity (specifies item quantity)
            qty_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_QTY,
                f"47{self.component_separator}{quantity}{self.component_separator}{unit}"
            )
            segments.append(qty_segment)
            self.logger.debug("Added segment: QTY for item %d", index)
            
            # PRI: Price (specifies unit price)
            pri_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_PRI,
                f"AAA{self.component_separator}{price:.2f}{self.component_separator}{unit}"
            )
            segments.append(pri_segment)
            self.logger.debug("Added segment: PRI for item %d", index)
            
            # Add tax segments if applicable
            if tax_rate > 0:
                tax_value = (line_total * tax_rate) / Decimal("100")
                total_tax += tax_value
                
                # TAX: Tax details (specifies tax type and rate)
                tax_segment = self._build_segment(
                    EDIFACTConfig.SEGMENT_TAX,
                    "7",
                    EDIFACTConfig.VAT_TAX_CATEGORY,
                    "",
                    "",
                    f"{tax_rate:.2f}",
                    "S"
                )
                segments.append(tax_segment)
                self.logger.debug("Added segment: TAX for item %d", index)
                
                # MOA: Monetary amount (specifies tax amount for item)
                moa_tax_segment = self._build_segment(
                    EDIFACTConfig.SEGMENT_MOA,
                    f"125{self.component_separator}{tax_value:.2f}"
                )
                segments.append(moa_tax_segment)
                self.logger.debug("Added segment: MOA for item %d (tax)", index)
        
        return total_amount, total_tax, segments
    
    def _generate_monetary_segments(
        self,
        total_amount: Decimal,
        total_tax: Decimal
    ) -> List[str]:
        """Generate MOA segments for monetary totals"""
        grand_total = total_amount + total_tax
        segments = [
            self._build_segment(
                EDIFACTConfig.SEGMENT_MOA,
                f"86{self.component_separator}{total_amount:.2f}"
            ),  # Total before tax
            self._build_segment(
                EDIFACTConfig.SEGMENT_MOA,
                f"176{self.component_separator}{total_tax:.2f}"
            ),  # Total tax
            self._build_segment(
                EDIFACTConfig.SEGMENT_MOA,
                f"9{self.component_separator}{grand_total:.2f}"
            )  # Invoice total
        ]
        return segments
    
    def _generate_payment_segments(self, payment_terms: Dict[str, Any], date_format: str) -> List[str]:
        """Generate PAT and DTM segments for payment terms"""
        segments = []
        if "due_date" in payment_terms:
            payment_method = EDIFACTValidator.sanitize_value(
                payment_terms.get("method", EDIFACTConfig.BANK_TRANSFER_PAYMENT)
            )
            
            pat_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_PAT,
                "1",
                "",
                payment_method
            )
            segments.append(pat_segment)
            
            dtm_segment = self._build_segment(
                EDIFACTConfig.SEGMENT_DTM,
                f"13{self.component_separator}{payment_terms['due_date']}{self.component_separator}102"
            )
            segments.append(dtm_segment)
            
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
    """Generate example INVOIC data for testing with enhanced information"""
    return {
        "message_ref": "INV2025001",
        "invoice_number": "INV2025001",
        "invoice_date": "20250322",
        "currency": "EUR",
        "reference": "PO12345",
        "parties": [
            {
                "qualifier": "BY", 
                "id": "123456789",
                "name": "ACME Corporation",
                "street": "123 Main Street",
                "city": "New York",
                "country": "US"
            },  # Buyer
            {
                "qualifier": "SU", 
                "id": "987654321",
                "name": "Widgets Inc",
                "street": "456 Industrial Ave",
                "city": "Chicago",
                "country": "US"
            },  # Supplier
            {
                "qualifier": "IV", 
                "id": "555555555",
                "name": "Invoice Department",
                "street": "123 Main Street",
                "city": "New York",
                "country": "US"
            }   # Invoicee
        ],
        "items": [
            {
                "product_code": "ABC123",
                "description": "Premium Widget",
                "quantity": "10",
                "price": "25.50",
                "tax_rate": "20",
                "unit": "PCE"
            },
            {
                "product_code": "XYZ456",
                "description": "Deluxe Gadget",
                "quantity": "5",
                "price": "40.00",
                "tax_rate": "20",
                "unit": "PCE"
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
    parser.add_argument("--interchange-ref", help="Interchange control reference")
    parser.add_argument("--application-ref", default="PYEDIFACT", help="Application reference")
    parser.add_argument("--character-set", default="UNOA", choices=["UNOA", "UNOB"], 
                       help="Character set (default: UNOA)")
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
            character_set=args.character_set,
            force=args.force,
            interchange_control_ref=args.interchange_ref,
            application_ref=args.application_ref
        )
        
        print("\nGenerated INVOIC Message:\n")
        print(edi_message)
        print(f"\nInvoice saved to '{args.output}'")
    except (EDIFACTGeneratorError, OSError, json.JSONDecodeError) as e:
        logger.error("Failed to generate INVOIC: %s", e)
        exit(1)
