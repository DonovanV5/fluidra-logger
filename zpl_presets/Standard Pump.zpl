^XA
^FX FMS_LABEL_SIZE_MM=65x35
^FX Top section with logo, name and address.
^CF0,60
^CF0,30
^FO50,20^FDFluidra Waterlinx (Pty) Ltd^FS
^FO50,50^GB450,3,3^FS
^FX Second section with recipient address and permit information.
^CFA,30
^FO50,60^FDPC        :{PC}^FS
^FO50,90^FDSerial#  :{barcode_text}^FS
^FO50,120^FDMD        :{timestamp}^FS
^CF0,100
^CFA,15
^FX Third section with bar code.
^BY2,2,80
^FO50,160^BC^FD{Barc}^FS
^XZ