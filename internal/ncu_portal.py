import httpx
import base64
import logging
from typing import Dict, List, Any, Optional
from core.config import settings

logger = logging.getLogger(__name__)

class NCUPortalClient:
    def __init__(self):
        self.client_id = settings.ncu_oauth_client_id
        self.client_secret = settings.ncu_oauth_client_secret
        
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        self.basic_headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Accept": "application/json"
        }
        # In-memory cache for lookup tables
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    async def _fetch_lookup(self, endpoint_url: str, cache_key: str) -> List[Dict[str, Any]]:
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(endpoint_url, headers=self.basic_headers)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    self._cache[cache_key] = data
                    return data
                else:
                    logger.warning(f"Lookup API {endpoint_url} returned non-list data: {data}")
            except Exception as e:
                logger.error(f"Error fetching lookup table from {endpoint_url}: {e}")
        return []

    async def get_study_systems(self) -> List[Dict[str, Any]]:
        return await self._fetch_lookup("https://portal.ncu.edu.tw/apis/ncu/studySystems", "study_systems")

    async def get_academics_units(self) -> List[Dict[str, Any]]:
        return await self._fetch_lookup("https://portal.ncu.edu.tw/apis/ncu/academicsUnits", "academics_units")

    async def get_units(self) -> List[Dict[str, Any]]:
        return await self._fetch_lookup("https://portal.ncu.edu.tw/apis/ncu/units", "units")

    async def get_titles(self) -> List[Dict[str, Any]]:
        return await self._fetch_lookup("https://portal.ncu.edu.tw/apis/ncu/titles", "titles")

    async def get_em_types(self) -> List[Dict[str, Any]]:
        return await self._fetch_lookup("https://portal.ncu.edu.tw/apis/ncu/emTypes", "em_types")

    async def get_es_types(self) -> List[Dict[str, Any]]:
        return await self._fetch_lookup("https://portal.ncu.edu.tw/apis/ncu/esTypes", "es_types")

    async def get_student_status(self) -> List[Dict[str, Any]]:
        return await self._fetch_lookup("https://portal.ncu.edu.tw/apis/ncu/studentStatus", "student_status")

    async def resolve_student_info(self, academy_record: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """
        Resolves studySystemNo, degreeKindNo, studentStatus from lookup tables.
        """
        resolved = {
            "study_system": None,
            "department": academy_record.get("name"),  # Direct name (e.g., "通訊工程學系")
            "student_status": None
        }
        
        study_system_no = academy_record.get("studySystemNo")
        degree_kind_no = academy_record.get("degreeKindNo")
        student_status_id = academy_record.get("studentStatus")

        # Resolve study system
        if study_system_no:
            systems = await self.get_study_systems()
            for s in systems:
                if str(s.get("studySystemNo")) == str(study_system_no):
                    resolved["study_system"] = s.get("studySystemCname")
                    break
        
        # Resolve department (academics units) as a fallback
        if not resolved["department"] and degree_kind_no:
            units = await self.get_academics_units()
            for u in units:
                if str(u.get("degreeKindNo")) == str(degree_kind_no):
                    resolved["department"] = u.get("degreeKindCname")
                    break

        # Resolve student status
        if student_status_id is not None:
            statuses = await self.get_student_status()
            for st in statuses:
                if str(st.get("statusId")) == str(student_status_id):
                    resolved["student_status"] = st.get("statusName")
                    break
                    
        return resolved

    async def resolve_faculty_info(self, faculty_record: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """
        Resolves unitNo, emTypeNo, esTypeNo, occupation from lookup tables.
        """
        resolved = {
            "department": faculty_record.get("unit"),  # Direct unit name
            "employee_type": None,
            "employee_status": None,
            "title": None
        }
        
        unit_no = faculty_record.get("unitNo")
        em_type_no = faculty_record.get("emTypeNo")
        es_type_no = faculty_record.get("esTypeNo")
        occupation = faculty_record.get("occupation")

        # Resolve department (units) as a fallback
        if not resolved["department"] and unit_no:
            units = await self.get_units()
            for u in units:
                if str(u.get("unitNo")) == str(unit_no):
                    resolved["department"] = u.get("unitCname")
                    break

        # Resolve employee type
        if em_type_no:
            em_types = await self.get_em_types()
            for et in em_types:
                if str(et.get("eMtypeNo")) == str(em_type_no):
                    resolved["employee_type"] = et.get("eMtypeCname")
                    break

        # Resolve employee status
        if es_type_no:
            es_types = await self.get_es_types()
            for est in es_types:
                if str(est.get("eStypeNo")) == str(es_type_no):
                    if em_type_no and str(est.get("eMtypeNo")) != str(em_type_no):
                        continue
                    resolved["employee_status"] = est.get("eStypeCname")
                    break

        # Resolve title from occupation
        if occupation:
            titles = await self.get_titles()
            title_found = False
            for t in titles:
                if str(t.get("titleNo")) == str(occupation):
                    resolved["title"] = t.get("titleCname")
                    title_found = True
                    break
            if not title_found:
                # Fallback to occupation name string if not matching any code
                resolved["title"] = occupation

        return resolved
