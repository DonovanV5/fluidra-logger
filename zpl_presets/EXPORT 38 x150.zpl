^XA
^FX FMS_LABEL_SIZE_MM=38x150
^FWR     <-- This command rotates all following fields 90 degrees clockwise
^PW{width_dots}
^LL{height_dots}
^FX 
^CF0,60
^CF0,30
^FO50,80^FDSerial#      :{barcode_text}^FS
^FO100,80^FDProduct Code :{PC}^FS
^FO200,80^FDDescription  :{desc1}^FS
^FO150,80^FD 	    	 :{desc2}^FS
^FO250,80^FDMD           :{timestamp}^FS
^BY4,2,200

^FO50,650^BC^FD{Barc}^FS
^XZ
