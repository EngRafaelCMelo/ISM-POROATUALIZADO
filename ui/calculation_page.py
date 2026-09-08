from __future__ import annotations
import json
from datetime import datetime
from typing import Any
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox,QDoubleSpinBox,QFormLayout,QFrame,QHBoxLayout,QHeaderView,QLabel,QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QTabWidget,QVBoxLayout,QWidget
from core.models import Measurement, TestDefinition
from core.permeability import GAS_PROPERTIES,absolute_pressure_kpa,calculate_gas_permeability,calculate_klinkenberg

def field(minimum=0., maximum=1_000_000., decimals=5, suffix=""):
    w=QDoubleSpinBox(); w.setRange(minimum,maximum); w.setDecimals(decimals); w.setSuffix(f" {suffix}" if suffix else ""); return w
def card():
    f=QFrame(); f.setObjectName("card"); return f,QVBoxLayout(f)

class CalculationPage(QWidget):
    save_requested=Signal(str,object,object,str)
    def __init__(self,config:dict[str,Any]):
        super().__init__(); self.config=config; self.definition=None; self.current_measurement=None; self.last_permeability=None; self.last_klinkenberg=None; self._dirty_results=set()
        root=QVBoxLayout(self); title=QLabel("Permeabilidade"); title.setObjectName("pageTitle"); root.addWidget(title); root.addWidget(QLabel("Calcule a permeabilidade de gás compressível, registre condições estáveis e aplique Klinkenberg opcionalmente."))
        self.banner=QLabel("Nenhum ensaio ativo"); self.banner.setObjectName("simulationBanner"); root.addWidget(self.banner)
        sample,sl=card(); form=QFormLayout(); self.length=field(suffix="mm"); self.diameter=field(suffix="mm"); self.gas=QComboBox()
        for key,p in GAS_PROPERTIES.items(): self.gas.addItem(p["nome"],key)
        self.temperature=field(-100,300,2,"°C"); self.temperature.setValue(20); self.viscosity=field(.001,1000,4,"µPa·s"); self.atmospheric=field(50,120,3,"kPa"); self.atmospheric.setValue(config["calculos"].get("pressao_atmosferica_kpa",101.325)); self.unit=QComboBox(); self.unit.addItems(["bar","kPa","MPa","psi"]); self.reference=QComboBox(); self.reference.addItem("Manométrica","manometrica"); self.reference.addItem("Absoluta","absoluta")
        for n,w in [("Comprimento",self.length),("Diâmetro",self.diameter),("Gás",self.gas),("Temperatura",self.temperature),("Viscosidade",self.viscosity),("Pressão atmosférica",self.atmospheric),("Unidade de pressão",self.unit),("Referência",self.reference)]: form.addRow(n,w)
        sl.addLayout(form); root.addWidget(sample)
        tabs=QTabWidget(); tabs.addTab(self._permeability_tab(),"Permeabilidade"); tabs.addTab(self._history_tab(),"Resultados salvos"); root.addWidget(tabs,1); self.gas.currentIndexChanged.connect(self._apply_gas); self._apply_gas()
    def _permeability_tab(self):
        page=QWidget(); layout=QHBoxLayout(page); left,ll=card(); form=QFormLayout(); self.inlet=field(-1000); self.outlet=field(-1000); self.flow=field(0,1e6,6,"L/min"); self.flow_ref=field(.001,1e6,5,"kPa abs"); self.flow_ref.setValue(101.325); self.outlet_mode=QComboBox(); self.outlet_mode.addItem("Informada manualmente","manual"); self.outlet_mode.addItem("Fixa configurada","fixed"); self.outlet_mode.addItem("Saída aberta à atmosfera","atmosphere")
        for n,w in [("Pressão de entrada",self.inlet),("Pressão de saída",self.outlet),("Modo da pressão de saída",self.outlet_mode),("Vazão",self.flow),("Referência da vazão",self.flow_ref)]: form.addRow(n,w)
        ll.addLayout(form); self.current=QLabel("Leituras: pressão — | vazão —"); ll.addWidget(self.current); b=QPushButton("Capturar entrada e vazão"); b.clicked.connect(self._capture); ll.addWidget(b); b=QPushButton("Calcular permeabilidade"); b.setObjectName("primary"); b.clicked.connect(self._calculate); ll.addWidget(b); self.result=QTableWidget(0,2); self.result.setHorizontalHeaderLabels(["Grandeza","Resultado"]); self.result.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch); ll.addWidget(self.result); self.save_permeability=QPushButton("Salvar resultado"); self.save_permeability.setEnabled(False); self.save_permeability.clicked.connect(lambda:self._save("Permeabilidade a gás",self.last_permeability)); ll.addWidget(self.save_permeability); layout.addWidget(left)
        right,rl=card(); h=QLabel("Correção de Klinkenberg"); h.setObjectName("sectionTitle"); rl.addWidget(h); self.points=QTableWidget(0,2); self.points.setHorizontalHeaderLabels(["Pressão média (kPa abs)","k aparente (mD)"]); self.points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); rl.addWidget(self.points); add=QPushButton("Adicionar resultado atual"); add.clicked.connect(self._add_point); rl.addWidget(add); kb=QPushButton("Calcular Klinkenberg"); kb.clicked.connect(self._klinkenberg); rl.addWidget(kb); self.kresult=QTableWidget(0,2); self.kresult.setHorizontalHeader().setVisible(True) if False else None; rl.addWidget(self.kresult); self.save_klinkenberg=QPushButton("Salvar correção"); self.save_klinkenberg.setEnabled(False); self.save_klinkenberg.clicked.connect(lambda:self._save("Klinkenberg",self.last_klinkenberg)); rl.addWidget(self.save_klinkenberg); layout.addWidget(right); return page
    def _history_tab(self):
        page=QWidget(); l=QVBoxLayout(page); self.history=QTableWidget(0,4); self.history.setHorizontalHeaderLabels(["Data","Tipo","Resultado","Observações"]); l.addWidget(self.history); return page
    def _apply_gas(self): self.viscosity.setValue(float(GAS_PROPERTIES[self.gas.currentData()]["viscosidade_upa_s"]))
    def set_session(self,definition:TestDefinition|None,context="active"):
        self.definition=definition; self.banner.setText(f"Ensaio: {definition.code} — {definition.sample_name}" if definition else "Nenhum ensaio selecionado")
        if definition: self.length.setValue(definition.sample_length_mm or 0); self.diameter.setValue(definition.sample_diameter_mm or 0); self.temperature.setValue(definition.temperature_c); self.unit.setCurrentText(definition.pressure_unit); self.reference.setCurrentIndex(max(0,self.reference.findData(definition.pressure_reference))); self.gas.setCurrentIndex(max(0,self.gas.findData(definition.gas_type)))
    def update_measurement(self,m:Measurement):
        self.current_measurement=m; self.current.setText(f"Leituras: pressão {m.pressure.value if m.pressure.value is not None else '—'} | vazão {m.flow.value if m.flow.value is not None else '—'}")
    def _capture(self):
        if not self.current_measurement: return QMessageBox.information(self,"Aguardando leituras","Conecte o ESP32 ou inicie o simulador.")
        if self.current_measurement.pressure.value is not None:self.inlet.setValue(self.current_measurement.pressure.value)
        if self.current_measurement.flow.value is not None:self.flow.setValue(self.current_measurement.flow.value)
    def _outlet_absolute(self):
        mode=self.outlet_mode.currentData()
        if mode=="atmosphere": return self.atmospheric.value()
        return absolute_pressure_kpa(self.outlet.value(),self.unit.currentText(),self.reference.currentData(),self.atmospheric.value())
    def _calculate(self):
        try:
            r=calculate_gas_permeability(flow_l_min=self.flow.value(),viscosity_upa_s=self.viscosity.value(),length_mm=self.length.value(),diameter_mm=self.diameter.value(),inlet_pressure_kpa_abs=absolute_pressure_kpa(self.inlet.value(),self.unit.currentText(),self.reference.currentData(),self.atmospheric.value()),outlet_pressure_kpa_abs=self._outlet_absolute(),flow_reference_pressure_kpa_abs=self.flow_ref.value()); inputs={"gas":self.gas.currentData(),"temperatura_c":self.temperature.value(),"comprimento_mm":self.length.value(),"diametro_mm":self.diameter.value(),"modo_pressao_saida":self.outlet_mode.currentData(),"simulado":bool(self.current_measurement and self.current_measurement.simulated)}; self.last_permeability=(inputs,r.as_dict()); self._dirty_results.add("Permeabilidade a gás"); self.save_permeability.setEnabled(self.definition is not None); self._rows(self.result,[("Permeabilidade",f"{r.permeability_m2:.6e} m²"),("Permeabilidade",f"{r.permeability_darcy:.6g} D"),("Permeabilidade",f"{r.permeability_md:.6g} mD"),("ΔP",f"{r.pressure_drop_kpa:.6g} kPa")])
        except ValueError as e: QMessageBox.warning(self,"Permeabilidade",str(e))
    def _add_point(self):
        if self.last_permeability:
            r=self.last_permeability[1]; row=self.points.rowCount(); self.points.insertRow(row); self.points.setItem(row,0,QTableWidgetItem(str(r["mean_pressure_kpa_abs"]))); self.points.setItem(row,1,QTableWidgetItem(str(r["permeability_md"])))
    def _klinkenberg(self):
        try:
            r=calculate_klinkenberg([(float(self.points.item(i,0).text()),float(self.points.item(i,1).text())) for i in range(self.points.rowCount())]); self.last_klinkenberg=({},r.as_dict()); self._dirty_results.add("Klinkenberg"); self.save_klinkenberg.setEnabled(self.definition is not None); self._rows(self.kresult,[("Permeabilidade intrínseca",f"{r.intrinsic_permeability_md:.6g} mD"),("b",f"{r.slip_factor_kpa:.6g} kPa"),("R²",f"{r.r_squared:.6f}")])
        except (ValueError,AttributeError) as e: QMessageBox.warning(self,"Klinkenberg",str(e))
    @staticmethod
    def _rows(table,rows):
        table.setRowCount(0)
        for a,b in rows: i=table.rowCount(); table.insertRow(i); table.setItem(i,0,QTableWidgetItem(a)); table.setItem(i,1,QTableWidgetItem(b))
    def _save(self,kind,data):
        if data:self.save_requested.emit(kind,*data,"")
    def pending_results(self): return [(k,d[0],d[1],"") for k,d in [("Permeabilidade a gás",self.last_permeability),("Klinkenberg",self.last_klinkenberg)] if d and k in self._dirty_results]
    def mark_saved(self,kind): self._dirty_results.discard(kind); (self.save_permeability if kind=="Permeabilidade a gás" else self.save_klinkenberg).setEnabled(False)
    def populate_history(self,rows):
        self.history.setRowCount(0)
        for r in rows:
            result=json.loads(r["resultados_json"]); i=self.history.rowCount(); self.history.insertRow(i); values=[datetime.fromisoformat(r["timestamp"]).strftime("%d/%m/%Y %H:%M"),r["tipo"],f"{result.get('permeability_md',result.get('intrinsic_permeability_md','—'))} mD",r["observacoes"] or ""]
            for j,v in enumerate(values): self.history.setItem(i,j,QTableWidgetItem(str(v)))
