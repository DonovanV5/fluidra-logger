import threading
import queue
import time
from typing import Optional

from zeep import Client, Settings
from zeep.transports import Transport
import requests


class TeraokaClient:
    def __init__(self, wsdl_url: str, workcenter: str, supervisor: str):
        self.wsdl_url = wsdl_url
        self.workcenter = workcenter
        self.supervisor = supervisor
        self._client: Optional[Client] = None
        self._wms_guid: Optional[str] = None
        self._current_job: Optional[str] = None
        self._product_code: Optional[str] = None
        self._required_quantity: Optional[int] = None
        self._total_quantity: Optional[int] = None
        self._qty_made: Optional[int] = None
        self._job_ts: float = 0.0
        self._q: "queue.Queue[int]" = queue.Queue()
        self._t: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_error: Optional[str] = None



    def start(self):
        if self._t and self._t.is_alive():
            return
        self._stop.clear()
        self._t = threading.Thread(target=self._worker, daemon=True)
        self._t.start()

    def shutdown(self):
        self._stop.set()
        try:
            self._q.put_nowait(None)  # type: ignore
        except Exception:
            pass
        if self._t:
            self._t.join(timeout=2.0)

    def enqueue_receipt(self, qty: int = 1):
        try:
            self._q.put_nowait(qty)
        except Exception:
            pass

    # --- Status accessors for UI ---
    def is_connected(self) -> bool:
        return self._client is not None and bool(self._wms_guid)

    def current_job(self) -> Optional[str]:
        return self._current_job
        
    def product_code(self) -> Optional[str]:
        return self._product_code
        
    def required_quantity(self) -> Optional[int]:
        return self._required_quantity
        
    def total_quantity(self) -> Optional[int]:
        return self._total_quantity
        
    def qty_made(self) -> Optional[int]:
        return self._qty_made

    def last_error(self) -> Optional[str]:
        return self._last_error

    def _worker(self):
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                # Proactively establish/refresh connection and job when idle
                try:
                    self._ensure_client()
                    self._ensure_login()
                    self._ensure_job()
                    self._last_error = None
                except Exception as e:
                    self._last_error = str(e)
                    time.sleep(0.5)
                continue
            if item is None:
                continue
            qty = int(item)
            try:
                self._ensure_client()
                self._ensure_login()
                self._ensure_job()
                if qty > 0 and self._current_job and self._wms_guid:
                    self._submit_receipt(self._current_job, qty)
            except Exception as e:
                self._last_error = str(e)
                time.sleep(1.0)
            finally:
                self._q.task_done()

    def _ensure_client(self):
        if self._client is not None:
            return
        session = requests.Session()
        transport = Transport(session=session, timeout=15)
        settings = Settings(strict=False, xml_huge_tree=True)
        self._client = Client(wsdl=self.wsdl_url, transport=transport, settings=settings)

    def _ensure_login(self):
        if self._wms_guid:
            return
        assert self._client is not None
        login_result = self._client.service.Login_WorkCenter(WorkCenter=self.workcenter)
        if getattr(login_result, 'LoggedInCorrectly', False):
            self._wms_guid = getattr(login_result, 'WMSGuid', '') or ''
            self._last_error = None
        else:
            msg = getattr(login_result, 'Message', 'Login failed')
            raise RuntimeError(str(msg))

    def _extract_field(self, obj, possible_fields):
        """Helper to extract a field from an object using a list of possible field names."""
        if obj is None:
            return None
            
        # Try direct attributes first
        for field in possible_fields:
            if hasattr(obj, field):
                value = getattr(obj, field)
                if value is not None and str(value).strip():
                    return value
                    
        # Try resultField if it exists
        if hasattr(obj, 'resultField'):
            return self._extract_field(getattr(obj, 'resultField'), possible_fields)
            
        return None

    def _ensure_job(self):
        now = time.time()
        if self._current_job and (now - self._job_ts) < 60:
            return
            
        assert self._client is not None
        assert self._wms_guid is not None
        
        # Reset values
        job = None
        self._product_code = None
        self._required_quantity = None
        self._total_quantity = None
        self._qty_made = None
        
        try:
            # Get workcenter data with debug logging
            print("\n=== Teraoka Workcenter Query ===")
            print(f"WorkCenter: {self.workcenter}, WMSGUID: {self._wms_guid}")
            
            # Get the raw response
            r = self._client.service.Workcenter_query(WorkCenter=self.workcenter, WMSGUID=self._wms_guid)
            print(f"\nRaw response type: {type(r)}")
            
            # Print all attributes of the response
            print("\nResponse attributes:")
            for attr in dir(r):
                if not attr.startswith('_'):
                    value = getattr(r, attr, None)
                    print(f"  {attr}: {value} (type: {type(value)})")
            
            # Print the response as a dictionary if possible
            if hasattr(r, '__dict__'):
                print("\nResponse as dict:")
                for key, value in r.__dict__.items():
                    print(f"  {key}: {value} (type: {type(value)})")
            
            # Print the raw XML response if available
            if hasattr(self._client, 'last_received') and self._client.last_received:
                print("\nRaw XML response:")
                print(self._client.last_received)
            
            if r is not None:
                # Extract job number
                job = self._extract_field(r, ['_JobField', 'Job', 'JobNumber', 'job', 'job_number', 'JobNo', 'JobID'])
                print(f"\nExtracted job: {job}")
                
                # Extract product code and quantity from resultField
                result = getattr(r, 'resultField', None)
                if result is not None:
                    # Get product code from _stockCodeField
                    if hasattr(result, '_stockCodeField'):
                        self._product_code = str(getattr(result, '_stockCodeField', '')).strip()
                        print(f"Found product code: {self._product_code}")
                    
                    # Get outstanding quantity from _TotalQtyOutstandingField
                    if hasattr(result, '_TotalQtyOutstandingField'):
                        qty = getattr(result, '_TotalQtyOutstandingField')
                        try:
                            self._required_quantity = int(float(qty))
                            print(f"Found required quantity: {self._required_quantity}")
                        except (ValueError, TypeError) as e:
                            print(f"Warning: Could not convert quantity '{qty}' to integer: {e}")
                    
                    # Get total quantity to make from _TotalQtyTomakeField
                    if hasattr(result, '_TotalQtyTomakeField'):
                        total_qty = getattr(result, '_TotalQtyTomakeField')
                        try:
                            self._total_quantity = int(float(total_qty))
                            print(f"Found total quantity to make: {self._total_quantity}")
                        except (ValueError, TypeError) as e:
                            print(f"Warning: Could not convert total quantity '{total_qty}' to integer: {e}")
                    
                    # Get quantity made from _TotalQtyMadeField
                    if hasattr(result, '_TotalQtyMadeField'):
                        qty_made = getattr(result, '_TotalQtyMadeField')
                        try:
                            self._qty_made = int(float(qty_made))
                            print(f"Found quantity made: {self._qty_made}")
                        except (ValueError, TypeError) as e:
                            print(f"Warning: Could not convert quantity made '{qty_made}' to integer: {e}")
                    
                    # For debugging, show what we found
                    print(f"Final product code: {self._product_code}")
                    print(f"Outstanding quantity: {self._required_quantity}")
                    print(f"Total quantity to make: {self._total_quantity}")
                    print(f"Quantity made: {self._qty_made}")
            
            if not job:
                print("Error: No job found in response")
                raise RuntimeError("No current job")
                
            self._current_job = str(job).strip()
            self._job_ts = now
            self._last_error = None
            print("=== End of Workcenter Query ===\n")
            
        except Exception as e:
            print(f"Error in _ensure_job: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _submit_receipt(self, job: str, qty: int):
        assert self._client is not None
        assert self._wms_guid is not None
        params = {
            'WorkCenter': self.workcenter,
            'Job': job,
            'ReceiptQty': int(qty),
            'WMSGUID': self._wms_guid,
            'Supervisor': self.supervisor,
        }
        self._client.service.Job_Receipt(**params)
