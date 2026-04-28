import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

# ============================================================================
# VIENOVO BRAND CONFIGURATION
# ============================================================================

# Vienovo Brand Colors
VNV = {
    'dark': '#0A3622',      # Primary dark green
    'primary': '#145A32',   # Main brand green
    'mid': '#1E8449',       # Medium green
    'accent': '#27AE60',    # Accent green
    'light': '#82E0AA',     # Light green
    'pale': '#D5F5E3',      # Very light green
    'surface': '#F0FAF4',   # Background tint
    'white': '#FFFFFF',
    'text': '#1C2833',      # Dark text
    'muted': '#707B7C',     # Muted text
    'danger': '#C0392B',    # Red
    'danger_bg': '#FDEDEC',
    'warning': '#E67E22',   # Orange
    'warning_bg': '#FEF5E7',
    'info': '#2E86C1',      # Blue
    'info_bg': '#EBF5FB',
    'gold': '#D4AC0D',
}

EQUIPMENT_MAP = {
    'GS': 'Global Start', 'B9B_ML': 'Bin 9B (Mill Line)', 'B4B_ML': 'Bin 4B (Mill Line)',
    'B6A_ML': 'Bin 6A (Mill Line)', 'BA1_ML': 'Batching / Weighing', 'HM14_ML': 'Hammermill 14',
    'MIX07_ML': 'Mixer 07', 'MH11_ML': 'Mixing Hopper 11', 'HP1': 'Hopper 1',
    'PEL11_PL': 'Pelletmill 11', 'COOLER14_PL': 'Cooler 14', 'SIF21': 'Sifter 21',
    'TRF_PL': 'Transfer (Pellet Line)', 'P2A_PL': 'Position 2A (Pellet Line)',
    'P3A_PL': 'Position 3A (Pellet Line)', 'P5B_PL': 'Position 5B (Pellet Line)',
    'P6B_PL': 'Position 6B (Pellet Line)',
}

EQUIPMENT_DESC = {
    'MS-01.1-D2': {'name': 'Mixer 01 — Dosing Line 2', 'type': 'Mixer / Dosing', 'critical': True,
        'desc': 'Controls ingredient dispensing into Mixer 01 on Line 2. Repeated alarms may indicate dosing calibration issues, sensor faults, or ingredient supply problems.'},
    'MS-01.1-D1': {'name': 'Mixer 01 — Dosing Line 1', 'type': 'Mixer / Dosing', 'critical': True,
        'desc': 'Controls dosing into Mixer 01 on Line 1. Issues here directly affect batch accuracy and formula compliance.'},
    'MS-1.1-PL': {'name': 'Mixer 1.1 — Pellet Line', 'type': 'Mixer / Dosing', 'critical': True,
        'desc': 'Mixer on the pellet production line. Alarms may indicate mixing faults or material flow issues before pelleting.'},
    'HL-02.1-D1': {'name': 'Hopper Level — Dosing 1', 'type': 'Hopper Level', 'critical': True,
        'desc': 'Monitors material level in the hopper feeding Dosing Line 1. Frequent alarms suggest the hopper runs empty often (supply issue) or the level sensor is faulty.'},
    'HL-02.1-HB': {'name': 'Hopper Level 02 — HM / Bin', 'type': 'Hopper Level', 'critical': False,
        'desc': 'Hopper level sensor near the hammermill / bin area. Monitors material availability before grinding.'},
    'HL-3A.1-PL': {'name': 'Hopper Level 3A — Pellet Line', 'type': 'Hopper Level', 'critical': True,
        'desc': 'Monitors material level feeding the pellet line. If empty, the pelletmill stops — causing production downtime.'},
    'VM-06-HB': {'name': 'Valve / Motor 06 — HM / Bin', 'type': 'Valve / Motor', 'critical': False,
        'desc': 'Controls a valve or motor in the hammermill area. Alarms may indicate mechanical jam, electrical fault, or overload.'},
}

FLOW_ORDER = {'GS':1,'B9B_ML':2,'B4B_ML':2,'B6A_ML':2,'BA1_ML':3,'HM14_ML':4,'MIX07_ML':5,
    'MH11_ML':6,'HP1':7,'PEL11_PL':8,'COOLER14_PL':9,'SIF21':10,'TRF_PL':11,
    'P2A_PL':12,'P3A_PL':12,'P5B_PL':12,'P6B_PL':12}

BATCH_STATE_MAP = {0:'Empty',1:'No Destination',2:'Idle',3:'Conflict',4:'Circuit Error',
    5:'Transferring',6:'Confirm Transfer',7:'Filling',8:'Mixing',9:'Waiting',10:'Waiting'}

INTAKE_STATE_MAP = {0:'Started',2:'In Progress',4:'Completed'}

# ============================================================================
# SMART ANALYSIS
# ============================================================================

def get_concern(count):
    if count >= 10: return 'HIGH', VNV['danger'], VNV['danger_bg']
    elif count >= 5: return 'MEDIUM', VNV['warning'], VNV['warning_bg']
    else: return 'LOW', VNV['mid'], VNV['pale']

def analyze_alarms(df):
    if df.empty or 'name' not in df.columns: return []
    results = []
    for equip, count in df['name'].value_counts().items():
        level, color, bg = get_concern(count)
        info = EQUIPMENT_DESC.get(equip, {'name':equip,'type':'Unknown','critical':False,'desc':'Equipment not yet mapped in system.'})
        if level == 'HIGH':
            if 'Hopper' in info.get('type',''):
                rec = 'Inspect hopper level sensor calibration. Check RM supply consistency from warehouse. Verify sensor wiring.'
            elif 'Mixer' in info.get('type',''):
                rec = 'Check dosing calibration and ingredient flow. Inspect mixer motor amps for overload. Verify dosing scale sensors.'
            else:
                rec = 'Investigate root cause immediately. Check maintenance logs. Schedule inspection within this shift.'
        elif level == 'MEDIUM':
            rec = 'Monitor closely. If alarms increase, schedule preventive maintenance. Check sensor calibration.'
        else:
            rec = 'Normal. Continue standard monitoring.'
        pattern = ''
        if 'dateApp' in df.columns:
            ea = df[df['name']==equip]
            ts = ea['dateApp'].max() - ea['dateApp'].min()
            if pd.notna(ts) and ts.total_seconds()>0 and count>2:
                avg = (ts.total_seconds()/(count-1))/60
                if avg < 5: pattern = f'RAPID — every {avg:.0f} min. Likely sensor issue or persistent fault that keeps re-triggering.'
                elif avg < 30: pattern = f'INTERMITTENT — every ~{avg:.0f} min. Comes and goes during production.'
                else: pattern = f'SCATTERED — ~{avg:.0f} min apart. May be triggered by specific production conditions.'
        results.append({'equip':equip,'name':info['name'],'type':info.get('type','Unknown'),
            'desc':info['desc'],'count':count,'level':level,'color':color,'bg':bg,
            'critical':info.get('critical',False),'rec':rec,'pattern':pattern})
    return sorted(results, key=lambda x: x['count'], reverse=True)

def analyze_batches(df):
    if df.empty: return []
    insights = []
    if 'IdBatch' in df.columns:
        for bid in df[df['IdBatch']>0]['IdBatch'].unique():
            bd = df[df['IdBatch']==bid]
            if 'State' in bd.columns:
                errs = bd[bd['State']==4]
                if len(errs)>0:
                    insights.append({'sev':'HIGH','msg':f'Batch {bid} — CIRCUIT ERROR on: {", ".join(errs["Equipment"].tolist())}',
                        'detail':'Equipment path is blocked or faulted. Check PLC for fault codes.'})
            if 'Duration_min' in bd.columns:
                for _,s in bd[bd['Duration_min']>60].iterrows():
                    insights.append({'sev':'MEDIUM','msg':f'Batch {bid} — {s["Equipment"]} took {s["Duration_min"]:.0f} min',
                        'detail':'Exceeds 60 min. Possible slowdown, material wait, or equipment issue.'})
    return insights

def analyze_intake(df):
    if df.empty: return []
    insights = []
    if 'StateDesc' in df.columns:
        total=len(df); comp=len(df[df['StateDesc']=='Completed']); prog=len(df[df['StateDesc']=='In Progress'])
        if prog > comp and total > 5:
            insights.append({'sev':'MEDIUM','msg':f'{prog} intakes "In Progress" vs {comp} "Completed"',
                'detail':'RM receiving may be slow or intake events not being properly closed in SCADA.'})
    if 'DateOperate' in df.columns and len(df)>2:
        tr = df['DateOperate'].max()-df['DateOperate'].min()
        if pd.notna(tr):
            hrs=tr.total_seconds()/3600; rate=len(df)/hrs if hrs>0 else 0
            insights.append({'sev':'INFO','msg':f'RM intake rate: {rate:.1f} events/hour ({hrs:.1f} hours covered)',
                'detail':'Average rate of raw material receiving activity in this data.'})
    return insights

# ============================================================================
# CSV PROCESSING
# ============================================================================

def read_csv_smart(f):
    raw=f.read(); f.seek(0)
    for enc in ['utf-8-sig','utf-8','cp1252','latin-1','utf-16']:
        try:
            if 'IdRow' in raw.decode(enc):
                df=pd.read_csv(f,encoding=enc); f.seek(0); return df
        except: f.seek(0)
    return pd.read_csv(f,encoding='latin-1')

def proc_fb(df):
    if df.empty: return df
    df['Equipment']=df['FBName'].map(EQUIPMENT_MAP).fillna(df['FBName'])
    df['FlowOrder']=df['FBName'].map(FLOW_ORDER).fillna(99)
    for c in ['DateStart','DateFinish']:
        if c in df.columns: df[c]=pd.to_datetime(df[c],errors='coerce')
    if 'DateStart' in df.columns and 'DateFinish' in df.columns:
        df['Duration_min']=(df['DateFinish']-df['DateStart']).dt.total_seconds().abs()/60
        df['Duration_min']=df['Duration_min'].round(1)
    if 'State' in df.columns: df['StateDesc']=df['State'].map(BATCH_STATE_MAP).fillna('Unknown')
    if 'BatchState' in df.columns: df['BatchStateDesc']=df['BatchState'].map(BATCH_STATE_MAP).fillna('Unknown')
    return df

def proc_al(df):
    if df.empty: return df
    for c in ['dateApp','DateDis']:
        if c in df.columns: df[c]=pd.to_datetime(df[c],errors='coerce')
    if 'dateApp' in df.columns and 'DateDis' in df.columns:
        df['AlarmDur_sec']=(df['DateDis']-df['dateApp']).dt.total_seconds().abs()
        df['AlarmDur_min']=(df['AlarmDur_sec']/60).round(1)
    if 'name' in df.columns:
        df['EquipType']=df['name'].apply(lambda x:x.split('-')[0] if isinstance(x,str) else '?')
        df['EquipTypeDesc']=df['EquipType'].map({'MS':'Mixer / Dosing','HL':'Hopper Level','VM':'Valve / Motor','PL':'Pellet Line'}).fillna(df['EquipType'])
    return df

def proc_in(df):
    if df.empty: return df
    if 'DateOperate' in df.columns: df['DateOperate']=pd.to_datetime(df['DateOperate'],errors='coerce')
    if 'State' in df.columns: df['StateDesc']=df['State'].map(INTAKE_STATE_MAP).fillna('Unknown')
    return df

# ============================================================================
# STREAMLIT PAGE CONFIG & STYLING
# ============================================================================

st.set_page_config(page_title="Vienovo — AC Plant SCADA Monitor", layout="wide", initial_sidebar_state="expanded")

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');

    .stApp {{
        font-family: 'Plus Jakarta Sans', sans-serif;
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {VNV['dark']} 0%, {VNV['primary']} 100%);
    }}
    [data-testid="stSidebar"] * {{
        color: {VNV['white']} !important;
    }}
    [data-testid="stSidebar"] .stRadio label {{
        color: {VNV['pale']} !important;
        font-weight: 500;
    }}
    [data-testid="stSidebar"] .stRadio label:hover {{
        color: {VNV['white']} !important;
    }}
    [data-testid="stSidebar"] hr {{
        border-color: rgba(255,255,255,0.15);
    }}

    /* Headers */
    h1 {{ color: {VNV['dark']}; font-weight: 800; letter-spacing: -0.5px; }}
    h2 {{ color: {VNV['primary']}; font-weight: 700; letter-spacing: -0.3px; }}
    h3 {{ color: {VNV['mid']}; font-weight: 600; }}

    /* Metrics */
    div[data-testid="stMetricValue"] {{
        font-size: 32px;
        font-weight: 800;
        color: {VNV['dark']};
    }}
    div[data-testid="stMetricLabel"] {{
        font-size: 12px;
        font-weight: 600;
        color: {VNV['muted']};
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    /* Alert Cards */
    .vnv-alert-high {{
        background: {VNV['danger_bg']};
        border-left: 5px solid {VNV['danger']};
        padding: 18px 24px;
        border-radius: 6px;
        margin-bottom: 14px;
        font-size: 14px;
        line-height: 1.6;
    }}
    .vnv-alert-med {{
        background: {VNV['warning_bg']};
        border-left: 5px solid {VNV['warning']};
        padding: 18px 24px;
        border-radius: 6px;
        margin-bottom: 14px;
        font-size: 14px;
        line-height: 1.6;
    }}
    .vnv-alert-ok {{
        background: {VNV['pale']};
        border-left: 5px solid {VNV['mid']};
        padding: 18px 24px;
        border-radius: 6px;
        margin-bottom: 14px;
        font-size: 14px;
        line-height: 1.6;
    }}
    .vnv-alert-info {{
        background: {VNV['info_bg']};
        border-left: 5px solid {VNV['info']};
        padding: 18px 24px;
        border-radius: 6px;
        margin-bottom: 14px;
        font-size: 14px;
        line-height: 1.6;
    }}

    /* Section headers */
    .vnv-section {{
        background: {VNV['surface']};
        padding: 12px 20px;
        border-radius: 8px;
        border-left: 4px solid {VNV['primary']};
        margin: 20px 0 12px 0;
        font-weight: 700;
        font-size: 15px;
        color: {VNV['dark']};
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }}

    /* Chart caption */
    .vnv-caption {{
        font-size: 12.5px;
        color: {VNV['muted']};
        line-height: 1.5;
        margin-bottom: 8px;
    }}

    /* Brand header */
    .vnv-brand {{
        background: linear-gradient(135deg, {VNV['dark']} 0%, {VNV['primary']} 100%);
        padding: 20px 30px;
        border-radius: 12px;
        margin-bottom: 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .vnv-brand h1 {{
        color: white !important;
        margin: 0;
        font-size: 28px;
    }}
    .vnv-brand span {{
        color: {VNV['light']};
        font-size: 14px;
        font-weight: 500;
    }}

    /* Badge */
    .vnv-badge-high {{ background:{VNV['danger']}; color:white; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:700; }}
    .vnv-badge-med {{ background:{VNV['warning']}; color:white; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:700; }}
    .vnv-badge-low {{ background:{VNV['mid']}; color:white; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:700; }}

    /* Hide Streamlit branding */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE
# ============================================================================

for k in ['fb','al','intake']:
    if k not in st.session_state: st.session_state[k]=pd.DataFrame()
if 'loaded' not in st.session_state: st.session_state.loaded=False
if 'updated' not in st.session_state: st.session_state.updated=None

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.markdown("### VIENOVO PHILIPPINES")
    st.caption("Feed for Life")
    st.markdown("---")
    page = st.radio("", ["Dashboard","Alarm Analysis","Batch Tracking","RM Intake","Upload Data","Data Explorer"])
    st.markdown("---")
    if st.session_state.loaded:
        st.markdown("**Data Status**")
        if st.session_state.updated: st.caption(f"Last update: {st.session_state.updated}")
        st.caption(f"FlowBatch — {len(st.session_state.fb)} rows")
        st.caption(f"Alarms — {len(st.session_state.al)} rows")
        st.caption(f"RM Intake — {len(st.session_state.intake)} rows")
    else:
        st.caption("No data loaded yet")
    st.markdown("---")
    st.caption("AC Plant — Bulacan")
    st.caption("CSV-based • Read-only")

# ============================================================================
# PLOTLY THEME
# ============================================================================

def style_fig(fig, height=380):
    fig.update_layout(
        font_family='Plus Jakarta Sans',
        font_color=VNV['text'],
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(t=15,b=15,l=15,r=15),
        height=height,
        legend=dict(font=dict(size=11)),
    )
    fig.update_xaxes(gridcolor='#E8E8E8', gridwidth=0.5)
    fig.update_yaxes(gridcolor='#E8E8E8', gridwidth=0.5)
    return fig

# ============================================================================
# UPLOAD
# ============================================================================

if page == "Upload Data":
    st.markdown(f"""<div class="vnv-brand"><div><h1>Upload SCADA Data</h1><span>AC Plant — Bulacan</span></div></div>""", unsafe_allow_html=True)
    st.markdown("Upload CSV files exported from the SCADA server (192.168.1.230). Dashboard updates instantly after upload.")
    st.markdown("---")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="vnv-section">FlowBatch</div>', unsafe_allow_html=True)
        st.caption("Production batch flow — tracks each batch through every equipment step")
        f1=st.file_uploader("Upload FlowBatch.csv",type=['csv'],key='u1')
        if f1: st.session_state.fb=proc_fb(read_csv_smart(f1)); st.success(f"{len(st.session_state.fb)} rows loaded")
    with c2:
        st.markdown(f'<div class="vnv-section">AlarmHistory</div>', unsafe_allow_html=True)
        st.caption("Equipment alarms and faults — identifies equipment needing attention")
        f2=st.file_uploader("Upload AlarmHistory.csv",type=['csv'],key='u2')
        if f2: st.session_state.al=proc_al(read_csv_smart(f2)); st.success(f"{len(st.session_state.al)} rows loaded")
    with c3:
        st.markdown(f'<div class="vnv-section">RPIntakeEvents</div>', unsafe_allow_html=True)
        st.caption("Raw material intake — tracks RM receiving and processing")
        f3=st.file_uploader("Upload RPIntakeEvents.csv",type=['csv'],key='u3')
        if f3: st.session_state.intake=proc_in(read_csv_smart(f3)); st.success(f"{len(st.session_state.intake)} rows loaded")
    if not st.session_state.fb.empty or not st.session_state.al.empty or not st.session_state.intake.empty:
        st.session_state.loaded=True; st.session_state.updated=datetime.now().strftime('%b %d, %Y %I:%M %p')

# ============================================================================
# DASHBOARD
# ============================================================================

elif page == "Dashboard":
    st.markdown(f"""<div class="vnv-brand"><div><h1>AC Plant — SCADA Dashboard</h1><span>Vienovo Philippines, Inc. • Feed for Life</span></div><div style="text-align:right;color:{VNV['light']};"><span style="font-size:13px;">Last updated</span><br><span style="font-size:16px;font-weight:600;">{st.session_state.updated or 'No data'}</span></div></div>""", unsafe_allow_html=True)

    if not st.session_state.loaded:
        st.info("No data loaded. Go to **Upload Data** in the sidebar."); st.stop()

    fb=st.session_state.fb; al=st.session_state.al; intake=st.session_state.intake
    aa=analyze_alarms(al); bi=analyze_batches(fb)

    # ── ALERTS ──
    st.markdown('<div class="vnv-section">ALERTS & ISSUES DETECTED</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="vnv-caption">Automated scan of SCADA data. <span class="vnv-badge-high">HIGH</span> = act now &nbsp; <span class="vnv-badge-med">MEDIUM</span> = monitor closely &nbsp; <span class="vnv-badge-low">LOW</span> = normal</p>', unsafe_allow_html=True)

    has_alerts=False
    for a in aa:
        if a['level'] in ['HIGH','MEDIUM']:
            has_alerts=True
            cls='vnv-alert-high' if a['level']=='HIGH' else 'vnv-alert-med'
            badge='vnv-badge-high' if a['level']=='HIGH' else 'vnv-badge-med'
            crit=' &nbsp;<span style="color:#C0392B;font-weight:700;">⚠ CRITICAL EQUIPMENT</span>' if a['critical'] else ''
            st.markdown(f"""<div class="{cls}">
                <table style="width:100%;border-collapse:collapse;"><tr>
                <td style="width:16%;vertical-align:top;padding-right:20px;">
                    <strong style="font-size:17px;">{a['equip']}</strong><br>
                    <span style="font-size:36px;font-weight:800;color:{a['color']};">{a['count']}</span><br>
                    <span class="{badge}">{a['level']}</span>{crit}
                </td>
                <td style="width:42%;vertical-align:top;padding-right:20px;">
                    <strong style="color:{VNV['dark']};">What it is</strong><br>
                    {a['name']} &nbsp;•&nbsp; <em>{a['type']}</em><br><br>
                    <span style="color:{VNV['muted']};">{a['desc']}</span>
                </td>
                <td style="width:42%;vertical-align:top;">
                    <strong style="color:{VNV['dark']};">Recommended Action</strong><br>
                    {a['rec']}
                    {f'<br><br><strong style="color:{VNV["dark"]};">Alarm Pattern</strong><br>{a["pattern"]}' if a['pattern'] else ''}
                </td></tr></table></div>""", unsafe_allow_html=True)

    for ins in bi:
        has_alerts=True
        cls='vnv-alert-high' if ins['sev']=='HIGH' else 'vnv-alert-med'
        st.markdown(f'<div class="{cls}"><strong>{ins["msg"]}</strong><br><span style="color:{VNV["muted"]};">{ins["detail"]}</span></div>', unsafe_allow_html=True)

    if not has_alerts:
        st.markdown(f'<div class="vnv-alert-ok"><strong style="color:{VNV["mid"]};">✓ ALL CLEAR</strong> &nbsp;— No high-concern issues detected in the current data.</div>', unsafe_allow_html=True)

    # ── KPIs ──
    st.markdown('<div class="vnv-section">OVERVIEW</div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5 = st.columns(5)
    ub=fb[fb['IdBatch']>0]['IdBatch'].nunique() if not fb.empty and 'IdBatch' in fb.columns else 0
    ac=len(fb[fb['State']==2]) if not fb.empty and 'State' in fb.columns else 0
    ta=len(al) if not al.empty else 0
    hc=len([x for x in aa if x['level']=='HIGH'])
    ic=len(intake) if not intake.empty else 0
    c1.metric("Batches",ub); c2.metric("Active Steps",ac); c3.metric("Total Alarms",ta)
    c4.metric("High Concern",hc); c5.metric("RM Events",ic)

    # ── CHARTS ROW 1 ──
    st.markdown('<div class="vnv-section">PRODUCTION & ALARMS</div>', unsafe_allow_html=True)
    c1,c2 = st.columns(2)

    with c1:
        st.markdown("**Batch Flow — Equipment Status**")
        st.markdown(f'<p class="vnv-caption">Current state of each equipment. <b>Transferring</b> = active. <b>Filling / Mixing</b> = processing. <b>Empty / Idle</b> = waiting for next batch.</p>', unsafe_allow_html=True)
        if not fb.empty and 'Equipment' in fb.columns:
            sd=fb[fb['IdBatch']>0].groupby(['Equipment','StateDesc']).size().reset_index(name='Count')
            if not sd.empty:
                fig=px.bar(sd,x='Equipment',y='Count',color='StateDesc',barmode='stack',
                    color_discrete_sequence=[VNV['dark'],VNV['mid'],VNV['light'],VNV['warning'],VNV['danger']])
                fig.update_layout(legend=dict(orientation='h',y=-0.35),xaxis_tickangle=-45)
                st.plotly_chart(style_fig(fig,400), use_container_width=True)

    with c2:
        st.markdown("**Alarm Count by Equipment**")
        st.markdown(f'<p class="vnv-caption">Longer bar = more alarms = needs attention. Color gradient: <span style="color:{VNV["mid"]};">■</span> green (OK) → <span style="color:{VNV["warning"]};">■</span> orange → <span style="color:{VNV["danger"]};">■</span> red (investigate).</p>', unsafe_allow_html=True)
        if not al.empty and 'name' in al.columns:
            ac2=al['name'].value_counts().head(10).reset_index(); ac2.columns=['Equipment','Count']
            fig=px.bar(ac2,x='Count',y='Equipment',orientation='h',color='Count',
                color_continuous_scale=[VNV['light'],VNV['warning'],VNV['danger']])
            fig.update_layout(yaxis={'categoryorder':'total ascending'},showlegend=False)
            st.plotly_chart(style_fig(fig,400), use_container_width=True)

    # ── CHARTS ROW 2 ──
    c1,c2 = st.columns(2)
    with c1:
        st.markdown("**Processing Time per Equipment**")
        st.markdown(f'<p class="vnv-caption">Average minutes per batch step. Unusually long bars may indicate slowdowns, material shortages, or equipment issues.</p>', unsafe_allow_html=True)
        if not fb.empty and 'Duration_min' in fb.columns:
            dd=fb[(fb['Duration_min']>0)&(fb['Duration_min']<1440)].groupby('Equipment')['Duration_min'].mean().sort_values(ascending=True).reset_index()
            if not dd.empty:
                fig=px.bar(dd,x='Duration_min',y='Equipment',orientation='h',color_discrete_sequence=[VNV['primary']])
                fig.update_layout(xaxis_title='Minutes')
                st.plotly_chart(style_fig(fig,400), use_container_width=True)

    with c2:
        st.markdown("**Alarm Timeline**")
        st.markdown(f'<p class="vnv-caption">Alarm frequency over time. Spikes = burst of issues. Look for patterns: shift changes, specific runs, or time-of-day trends.</p>', unsafe_allow_html=True)
        if not al.empty and 'dateApp' in al.columns:
            at2=al.copy(); at2['Hour']=at2['dateApp'].dt.floor('h')
            hr=at2.groupby('Hour').size().reset_index(name='Alarms')
            if not hr.empty:
                fig=px.area(hr,x='Hour',y='Alarms',color_discrete_sequence=[VNV['danger']])
                fig.update_traces(fillcolor=f"rgba(192,57,43,0.15)", line_color=VNV['danger'])
                st.plotly_chart(style_fig(fig,400), use_container_width=True)

    # ── ALARM BY TYPE ──
    st.markdown('<div class="vnv-section">ALARM BREAKDOWN</div>', unsafe_allow_html=True)
    c1,c2 = st.columns(2)
    with c1:
        st.markdown("**Alarms by Equipment Type**")
        st.markdown(f'<p class="vnv-caption">Groups by category. Shows whether the problem is system-wide (e.g., all hoppers) or isolated to one machine.</p>', unsafe_allow_html=True)
        if not al.empty and 'EquipTypeDesc' in al.columns:
            td=al['EquipTypeDesc'].value_counts().reset_index(); td.columns=['Type','Count']
            fig=px.pie(td,values='Count',names='Type',color_discrete_sequence=[VNV['dark'],VNV['primary'],VNV['mid'],VNV['accent'],VNV['danger']])
            fig.update_traces(textposition='inside',textinfo='percent+label',textfont_size=13)
            st.plotly_chart(style_fig(fig,380), use_container_width=True)

    with c2:
        st.markdown("**RM Intake Activity**")
        st.markdown(f'<p class="vnv-caption">When raw materials are being received. Peaks = busy receiving periods. Gaps = no activity.</p>', unsafe_allow_html=True)
        if not intake.empty and 'DateOperate' in intake.columns:
            ic2=intake.copy(); ic2['Hour']=ic2['DateOperate'].dt.floor('h')
            hr3=ic2.groupby('Hour').size().reset_index(name='Events')
            fig=px.bar(hr3,x='Hour',y='Events',color_discrete_sequence=[VNV['primary']])
            st.plotly_chart(style_fig(fig,380), use_container_width=True)

    # ── EQUIPMENT SUMMARY ──
    st.markdown('<div class="vnv-section">COMPLETE EQUIPMENT ALARM SUMMARY</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="vnv-caption">Every equipment that triggered alarms — concern level, description, and recommended action.</p>', unsafe_allow_html=True)

    for a in aa:
        cls='vnv-alert-high' if a['level']=='HIGH' else ('vnv-alert-med' if a['level']=='MEDIUM' else 'vnv-alert-ok')
        badge='vnv-badge-high' if a['level']=='HIGH' else ('vnv-badge-med' if a['level']=='MEDIUM' else 'vnv-badge-low')
        crit=' • CRITICAL' if a['critical'] else ''
        st.markdown(f"""<div class="{cls}">
            <table style="width:100%;border-collapse:collapse;"><tr>
            <td style="width:15%;vertical-align:top;padding-right:20px;">
                <strong style="font-size:15px;">{a['equip']}</strong><br>
                <span style="font-size:30px;font-weight:800;color:{a['color']};">{a['count']}</span><br>
                <span class="{badge}">{a['level']}{crit}</span>
            </td>
            <td style="width:42%;vertical-align:top;padding-right:20px;">
                <strong>What it is:</strong> {a['name']}<br>
                <strong>Type:</strong> {a['type']}<br><br>
                <span style="color:{VNV['muted']};">{a['desc']}</span>
            </td>
            <td style="width:43%;vertical-align:top;">
                <strong>Recommended Action:</strong><br>{a['rec']}
                {f'<br><br><strong>Pattern:</strong> {a["pattern"]}' if a['pattern'] else ''}
            </td></tr></table></div>""", unsafe_allow_html=True)

# ============================================================================
# ALARM ANALYSIS
# ============================================================================

elif page == "Alarm Analysis":
    st.markdown(f"""<div class="vnv-brand"><div><h1>Alarm Analysis</h1><span>AC Plant — Equipment Health Monitor</span></div></div>""", unsafe_allow_html=True)
    if st.session_state.al.empty: st.info("No alarm data. Go to **Upload Data**."); st.stop()
    al=st.session_state.al; aa=analyze_alarms(al)

    st.markdown('<div class="vnv-section">SMART ANALYSIS</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="vnv-caption">Each equipment is analyzed: alarm count, concern level, what it is, what\'s likely wrong, and what to do about it.</p>', unsafe_allow_html=True)

    for a in aa:
        cls='vnv-alert-high' if a['level']=='HIGH' else ('vnv-alert-med' if a['level']=='MEDIUM' else 'vnv-alert-ok')
        badge='vnv-badge-high' if a['level']=='HIGH' else ('vnv-badge-med' if a['level']=='MEDIUM' else 'vnv-badge-low')
        st.markdown(f"""<div class="{cls}">
            <table style="width:100%;border-collapse:collapse;"><tr>
            <td style="width:15%;vertical-align:top;">
                <strong style="font-size:16px;">{a['equip']}</strong><br>
                <span style="font-size:32px;font-weight:800;color:{a['color']};">{a['count']}</span><br>
                <span class="{badge}">{a['level']}</span>
            </td>
            <td style="width:42%;vertical-align:top;padding:0 20px;">
                <strong>What it is:</strong> {a['name']}<br><strong>Type:</strong> {a['type']}<br><br>
                <span style="color:{VNV['muted']};">{a['desc']}</span>
            </td>
            <td style="width:43%;vertical-align:top;">
                <strong>Recommended Action:</strong><br>{a['rec']}
                {f'<br><br><strong>Pattern:</strong> {a["pattern"]}' if a['pattern'] else ''}
            </td></tr></table></div>""", unsafe_allow_html=True)

    st.markdown("---")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Total Alarms",len(al))
    c2.metric("Equipment",al['name'].nunique() if 'name' in al.columns else 0)
    if 'AlarmDur_min' in al.columns:
        c3.metric("Avg Duration",f"{al['AlarmDur_min'].mean():.1f} min")
        c4.metric("Max Duration",f"{al['AlarmDur_min'].max():.1f} min")
    st.markdown("---")
    st.markdown('<div class="vnv-section">REPEAT ALARM EQUIPMENT</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="vnv-caption">If First and Last alarm are close together = burst of alarms. If far apart = recurring issue over time.</p>', unsafe_allow_html=True)
    if 'name' in al.columns:
        rp=al.groupby('name').agg(Alarms=('IdRow','count'),First=('dateApp','min'),Last=('dateApp','max')).sort_values('Alarms',ascending=False).reset_index()
        st.dataframe(rp, use_container_width=True, hide_index=True)
    st.markdown("---")
    st.markdown('<div class="vnv-section">FULL ALARM LOG</div>', unsafe_allow_html=True)
    dc=[c for c in ['name','dateApp','DateDis','AlarmDur_min','EquipTypeDesc'] if c in al.columns]
    st.dataframe(al[dc], use_container_width=True, hide_index=True)
    out=BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as w: al.to_excel(w,sheet_name='Alarms',index=False)
    out.seek(0)
    st.download_button("Download Alarm Report",data=out,file_name=f"VPI_AC_Alarms_{datetime.now().strftime('%Y%m%d')}.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============================================================================
# BATCH TRACKING
# ============================================================================

elif page == "Batch Tracking":
    st.markdown(f"""<div class="vnv-brand"><div><h1>Batch Tracking</h1><span>AC Plant — Production Flow Monitor</span></div></div>""", unsafe_allow_html=True)
    if st.session_state.fb.empty: st.info("No batch data. Go to **Upload Data**."); st.stop()
    fb=st.session_state.fb; bi=analyze_batches(fb)
    if bi:
        for ins in bi:
            cls='vnv-alert-high' if ins['sev']=='HIGH' else 'vnv-alert-med'
            st.markdown(f'<div class="{cls}"><strong>{ins["msg"]}</strong><br><span style="color:{VNV["muted"]};">{ins["detail"]}</span></div>', unsafe_allow_html=True)
    st.markdown("---")
    if 'IdBatch' in fb.columns:
        bids=sorted(fb[fb['IdBatch']>0]['IdBatch'].unique(),reverse=True)
        if bids:
            sb=st.selectbox("Select Batch",bids,format_func=lambda x:f"Batch {x}")
            bd=fb[fb['IdBatch']==sb].copy()
            if 'IdBatchPre' in fb.columns:
                bd=pd.concat([bd,fb[fb['IdBatchPre']==sb]]).drop_duplicates(subset=['IdRow']).sort_values('FlowOrder')
            if not bd.empty:
                c1,c2,c3,c4=st.columns(4)
                c1.metric("Batch",sb); c2.metric("Steps",len(bd))
                if 'DateStart' in bd.columns:
                    s=bd['DateStart'].min(); e=bd['DateFinish'].max()
                    if pd.notna(s): c3.metric("Started",s.strftime('%m/%d %I:%M %p'))
                    if pd.notna(e): c4.metric("Latest",e.strftime('%m/%d %I:%M %p'))
                st.markdown("---")
                st.markdown('<div class="vnv-section">PRODUCTION FLOW</div>', unsafe_allow_html=True)
                st.markdown(f'<p class="vnv-caption">Each row = one equipment step in the production process. Duration shows processing time. Watch for steps over 60 min.</p>', unsafe_allow_html=True)
                for _,row in bd.iterrows():
                    c1,c2,c3,c4=st.columns([3,2,2,1])
                    with c1:
                        st.markdown(f"**{row.get('Equipment',row.get('FBName','?'))}**")
                        st.caption(f"Tag: {row.get('FBName','')} • Order: {row.get('OrderFB','')}")
                    with c2:
                        if pd.notna(row.get('DateStart')): st.caption(f"Start: {row['DateStart'].strftime('%m/%d %I:%M %p')}")
                        if pd.notna(row.get('DateFinish')): st.caption(f"End: {row['DateFinish'].strftime('%m/%d %I:%M %p')}")
                    with c3:
                        if 'Duration_min' in row and row['Duration_min']>0:
                            d=row['Duration_min']
                            st.metric("Duration",f"{d:.0f} min" if d>60 else f"{d:.1f} min")
                            if d>60: st.caption("⚠ Longer than usual")
                    with c4:
                        state=row.get('StateDesc','Unknown')
                        if state=='Transferring': st.success(state)
                        elif state in ['Filling','Mixing']: st.warning(state)
                        elif state=='Circuit Error': st.error(state)
                        else: st.info(state)
                    st.markdown("---")

# ============================================================================
# RM INTAKE
# ============================================================================

elif page == "RM Intake":
    st.markdown(f"""<div class="vnv-brand"><div><h1>RM Intake Monitor</h1><span>AC Plant — Raw Material Receiving</span></div></div>""", unsafe_allow_html=True)
    if st.session_state.intake.empty: st.info("No intake data. Go to **Upload Data**."); st.stop()
    intake=st.session_state.intake; ii=analyze_intake(intake)
    if ii:
        for ins in ii:
            cls='vnv-alert-med' if ins['sev']=='MEDIUM' else 'vnv-alert-info'
            st.markdown(f'<div class="{cls}"><strong>{ins["msg"]}</strong><br><span style="color:{VNV["muted"]};">{ins["detail"]}</span></div>', unsafe_allow_html=True)
    st.markdown("---")
    c1,c2,c3=st.columns(3)
    c1.metric("Total Events",len(intake))
    if 'StateDesc' in intake.columns:
        c2.metric("Completed",len(intake[intake['StateDesc']=='Completed']))
        c3.metric("In Progress",len(intake[intake['StateDesc']=='In Progress']))
    st.markdown("---")
    c1,c2=st.columns(2)
    with c1:
        st.markdown("**Events by Status**")
        st.markdown(f'<p class="vnv-caption"><b>Started</b> = initiated &nbsp;•&nbsp; <b>In Progress</b> = receiving &nbsp;•&nbsp; <b>Completed</b> = done. Most should be Completed.</p>', unsafe_allow_html=True)
        if 'StateDesc' in intake.columns:
            sc=intake['StateDesc'].value_counts().reset_index(); sc.columns=['Status','Count']
            fig=px.pie(sc,values='Count',names='Status',color_discrete_sequence=[VNV['dark'],VNV['mid'],VNV['light']])
            fig.update_traces(textposition='inside',textinfo='percent+label',textfont_size=13)
            st.plotly_chart(style_fig(fig,350), use_container_width=True)
    with c2:
        st.markdown("**Activity Timeline**")
        st.markdown(f'<p class="vnv-caption">When RM intake happens. Peaks = busy receiving. Gaps = no activity (breaks, shift change).</p>', unsafe_allow_html=True)
        if 'DateOperate' in intake.columns:
            ic2=intake.copy(); ic2['Hour']=ic2['DateOperate'].dt.floor('h')
            hr=ic2.groupby('Hour').size().reset_index(name='Events')
            fig=px.bar(hr,x='Hour',y='Events',color_discrete_sequence=[VNV['primary']])
            st.plotly_chart(style_fig(fig,350), use_container_width=True)
    st.markdown("---")
    st.markdown('<div class="vnv-section">FULL INTAKE LOG</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="vnv-caption">State: 0 = Started, 2 = In Progress, 4 = Completed. IdIntake = delivery ID.</p>', unsafe_allow_html=True)
    st.dataframe(intake, use_container_width=True, hide_index=True)

# ============================================================================
# DATA EXPLORER
# ============================================================================

elif page == "Data Explorer":
    st.markdown(f"""<div class="vnv-brand"><div><h1>Data Explorer</h1><span>Raw SCADA Data Viewer</span></div></div>""", unsafe_allow_html=True)
    ds=st.selectbox("Dataset",["FlowBatch","AlarmHistory","RPIntakeEvents"])
    if ds=="FlowBatch" and not st.session_state.fb.empty: df=st.session_state.fb
    elif ds=="AlarmHistory" and not st.session_state.al.empty: df=st.session_state.al
    elif ds=="RPIntakeEvents" and not st.session_state.intake.empty: df=st.session_state.intake
    else: st.info(f"No {ds} data."); st.stop()
    c1,c2,c3=st.columns(3)
    c1.metric("Rows",len(df)); c2.metric("Columns",len(df.columns)); c3.metric("Dataset",ds)
    st.markdown("---")
    st.dataframe(df, use_container_width=True, hide_index=True)
    out=BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as w: df.to_excel(w,sheet_name=ds,index=False)
    out.seek(0)
    st.download_button(f"Download {ds}",data=out,file_name=f"VPI_AC_{ds}_{datetime.now().strftime('%Y%m%d')}.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
