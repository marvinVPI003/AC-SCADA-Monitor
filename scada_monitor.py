import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from io import BytesIO
import os
import glob

# ============================================================================
# CONFIGURATION
# ============================================================================

# Equipment name mapping (decoded from FlowBatch FBName)
EQUIPMENT_MAP = {
    'GS': 'Global Start',
    'B9B_ML': 'Bin 9B (Mill Line)',
    'B4B_ML': 'Bin 4B (Mill Line)',
    'B6A_ML': 'Bin 6A (Mill Line)',
    'BA1_ML': 'Batching/Weighing',
    'HM14_ML': 'Hammermill 14',
    'MIX07_ML': 'Mixer 07',
    'MH11_ML': 'Mixing Hopper 11',
    'HP1': 'Hopper 1',
    'PEL11_PL': 'Pelletmill 11',
    'COOLER14_PL': 'Cooler 14',
    'SIF21': 'Sifter 21',
    'TRF_PL': 'Transfer (Pellet Line)',
    'P2A_PL': 'Position 2A (Pellet Line)',
    'P3A_PL': 'Position 3A (Pellet Line)',
    'P5B_PL': 'Position 5B (Pellet Line)',
    'P6B_PL': 'Position 6B (Pellet Line)',
}

# Production flow order (sequence in the plant)
FLOW_ORDER = {
    'GS': 1,
    'B9B_ML': 2, 'B4B_ML': 2, 'B6A_ML': 2,
    'BA1_ML': 3,
    'HM14_ML': 4,
    'MIX07_ML': 5,
    'MH11_ML': 6,
    'HP1': 7,
    'PEL11_PL': 8,
    'COOLER14_PL': 9,
    'SIF21': 10,
    'TRF_PL': 11,
    'P2A_PL': 12, 'P3A_PL': 12, 'P5B_PL': 12, 'P6B_PL': 12,
}

# Batch state lookup
BATCH_STATE_MAP = {
    0: 'Empty', 1: 'No Destination', 2: 'Idle',
    3: 'Conflict', 4: 'Circuit Error', 5: 'Transferring',
    6: 'Confirm Transfer', 7: 'Filling', 8: 'Mixing',
    9: 'Waiting', 10: 'Waiting',
}

# RM Intake state lookup
INTAKE_STATE_MAP = {0: 'Started', 2: 'In Progress', 4: 'Completed'}

# Color palette
COLORS = {
    'primary': '#1B4332',
    'secondary': '#2D6A4F',
    'accent': '#40916C',
    'success': '#52B788',
    'warning': '#F77F00',
    'danger': '#D62828',
    'light': '#D8F3DC',
    'bg': '#F8F9FA',
    'text': '#212529',
}

# ============================================================================
# CSV READING
# ============================================================================

def read_csv_smart(uploaded_file):
    """Read CSV with encoding auto-detection"""
    raw = uploaded_file.read()
    uploaded_file.seek(0)
    
    for enc in ['utf-8-sig', 'utf-8', 'cp1252', 'latin-1', 'utf-16']:
        try:
            text = raw.decode(enc)
            if 'IdRow' in text or 'idRow' in text or 'TABLE_NAME' in text:
                df = pd.read_csv(uploaded_file, encoding=enc)
                uploaded_file.seek(0)
                return df
        except:
            uploaded_file.seek(0)
            continue
    
    # Fallback
    return pd.read_csv(uploaded_file, encoding='latin-1')


def read_csv_from_path(filepath):
    """Read CSV from file path with encoding auto-detection"""
    with open(filepath, 'rb') as f:
        raw = f.read()
    
    for enc in ['utf-8-sig', 'utf-8', 'cp1252', 'latin-1']:
        try:
            text = raw.decode(enc)
            if 'IdRow' in text or 'idRow' in text:
                return pd.read_csv(filepath, encoding=enc)
        except:
            continue
    return pd.read_csv(filepath, encoding='latin-1')


def process_flowbatch(df):
    """Process FlowBatch dataframe"""
    if df.empty:
        return df
    
    # Add readable equipment names
    df['Equipment'] = df['FBName'].map(EQUIPMENT_MAP).fillna(df['FBName'])
    
    # Add flow order for sorting
    df['FlowOrder'] = df['FBName'].map(FLOW_ORDER).fillna(99)
    
    # Parse dates
    for col in ['DateStart', 'DateFinish']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    
    # Calculate duration in minutes
    if 'DateStart' in df.columns and 'DateFinish' in df.columns:
        df['Duration_min'] = (df['DateFinish'] - df['DateStart']).dt.total_seconds() / 60
        df['Duration_min'] = df['Duration_min'].abs().round(1)
    
    # Add state description
    if 'State' in df.columns:
        df['StateDesc'] = df['State'].map(BATCH_STATE_MAP).fillna('Unknown')
    
    if 'BatchState' in df.columns:
        df['BatchStateDesc'] = df['BatchState'].map(BATCH_STATE_MAP).fillna('Unknown')
    
    return df


def process_alarms(df):
    """Process AlarmHistory dataframe"""
    if df.empty:
        return df
    
    for col in ['dateApp', 'DateDis']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    
    # Calculate alarm duration
    if 'dateApp' in df.columns and 'DateDis' in df.columns:
        df['AlarmDuration_sec'] = (df['DateDis'] - df['dateApp']).dt.total_seconds().abs()
        df['AlarmDuration_min'] = (df['AlarmDuration_sec'] / 60).round(1)
    
    # Extract equipment type from name
    if 'name' in df.columns:
        df['EquipType'] = df['name'].apply(lambda x: x.split('-')[0] if isinstance(x, str) else 'Unknown')
        df['EquipTypeDesc'] = df['EquipType'].map({
            'MS': 'Mixer/Dosing',
            'HL': 'Hopper Level',
            'VM': 'Valve/Motor',
            'PL': 'Pellet Line',
        }).fillna(df['EquipType'])
    
    return df


def process_intake(df):
    """Process RPIntakeEvents dataframe"""
    if df.empty:
        return df
    
    if 'DateOperate' in df.columns:
        df['DateOperate'] = pd.to_datetime(df['DateOperate'], errors='coerce')
    
    if 'State' in df.columns:
        df['StateDesc'] = df['State'].map(INTAKE_STATE_MAP).fillna('Unknown')
    
    return df


# ============================================================================
# PAGE SETUP
# ============================================================================

st.set_page_config(
    page_title="AC Plant SCADA Monitor",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap');
    
    .stApp {
        font-family: 'DM Sans', sans-serif;
    }
    
    div[data-testid="stMetricValue"] {
        font-size: 28px;
        font-weight: 700;
        color: #1B4332;
    }
    
    div[data-testid="stMetricLabel"] {
        font-size: 13px;
        font-weight: 500;
        color: #6C757D;
    }
    
    .block-container {
        padding-top: 1.5rem;
    }
    
    h1 { color: #1B4332; font-weight: 700; }
    h2 { color: #2D6A4F; font-weight: 600; }
    h3 { color: #40916C; font-weight: 600; }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    .stTabs [data-baseweb="tab"] {
        padding: 8px 20px;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# SESSION STATE
# ============================================================================

if 'flowbatch_df' not in st.session_state:
    st.session_state.flowbatch_df = pd.DataFrame()
if 'alarm_df' not in st.session_state:
    st.session_state.alarm_df = pd.DataFrame()
if 'intake_df' not in st.session_state:
    st.session_state.intake_df = pd.DataFrame()
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'last_update' not in st.session_state:
    st.session_state.last_update = None


# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.markdown("## AC Plant Monitor")
    st.caption("Vienovo Philippines, Inc.")
    st.markdown("---")
    
    page = st.radio("Navigation", [
        "Dashboard",
        "Batch Tracking",
        "Alarm Analysis",
        "RM Intake",
        "Upload New Data",
        "Data Explorer"
    ])
    
    st.markdown("---")
    
    if st.session_state.data_loaded:
        st.success("Data loaded")
        if st.session_state.last_update:
            st.caption(f"Updated: {st.session_state.last_update}")
        
        fb_count = len(st.session_state.flowbatch_df)
        al_count = len(st.session_state.alarm_df)
        in_count = len(st.session_state.intake_df)
        
        st.caption(f"FlowBatch: {fb_count} rows")
        st.caption(f"Alarms: {al_count} rows")
        st.caption(f"RM Intake: {in_count} rows")
    else:
        st.warning("No data loaded")
        st.caption("Go to 'Upload New Data' to load CSV files")
    
    st.markdown("---")
    st.caption("Read-only | No SCADA connection")


# ============================================================================
# UPLOAD PAGE
# ============================================================================

if page == "Upload New Data":
    st.title("Upload SCADA CSV Exports")
    st.markdown("Upload the CSV files exported from the SCADA server. The dashboard will update automatically.")
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("FlowBatch.csv")
        st.caption("Batch production flow data")
        fb_file = st.file_uploader("Upload FlowBatch", type=['csv'], key='fb_upload')
        if fb_file:
            df = read_csv_smart(fb_file)
            st.session_state.flowbatch_df = process_flowbatch(df)
            st.success(f"Loaded {len(df)} rows")
    
    with col2:
        st.subheader("AlarmHistory.csv")
        st.caption("Equipment alarm/fault data")
        al_file = st.file_uploader("Upload AlarmHistory", type=['csv'], key='al_upload')
        if al_file:
            df = read_csv_smart(al_file)
            st.session_state.alarm_df = process_alarms(df)
            st.success(f"Loaded {len(df)} rows")
    
    with col3:
        st.subheader("RPIntakeEvents.csv")
        st.caption("Raw material intake events")
        in_file = st.file_uploader("Upload RPIntakeEvents", type=['csv'], key='in_upload')
        if in_file:
            df = read_csv_smart(in_file)
            st.session_state.intake_df = process_intake(df)
            st.success(f"Loaded {len(df)} rows")
    
    if not st.session_state.flowbatch_df.empty or not st.session_state.alarm_df.empty or not st.session_state.intake_df.empty:
        st.session_state.data_loaded = True
        st.session_state.last_update = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    st.markdown("---")
    st.subheader("How to get fresh CSV files")
    st.markdown("""
    Ask your SCADA technician to run these queries in SQL Server Management Studio on the SCADA server (192.168.1.230), 
    then right-click the results → **Save Results As** → CSV:
    
    **FlowBatch** (production batch tracking):
    ```sql
    SELECT * FROM dbo.FlowBatch ORDER BY IdRow DESC
    ```
    
    **AlarmHistory** (last 7 days of alarms):
    ```sql
    SELECT TOP 500 * FROM dbo.AlarmHistory 
    WHERE dateApp >= DATEADD(day, -7, GETDATE()) 
    ORDER BY IdRow DESC
    ```
    
    **RPIntakeEvents** (last 7 days of RM intake):
    ```sql
    SELECT TOP 500 * FROM dbo.RpIntakeEvents 
    WHERE DateOperate >= DATEADD(day, -7, GETDATE()) 
    ORDER BY IdRow DESC
    ```
    """)


# ============================================================================
# DASHBOARD
# ============================================================================

elif page == "Dashboard":
    st.title("AC Plant SCADA Dashboard")
    
    if not st.session_state.data_loaded:
        st.info("No data loaded yet. Go to **Upload New Data** in the sidebar to load CSV files.")
        st.stop()
    
    st.markdown("---")
    
    fb = st.session_state.flowbatch_df
    al = st.session_state.alarm_df
    intake = st.session_state.intake_df
    
    # ---- KPI ROW ----
    col1, col2, col3, col4, col5 = st.columns(5)
    
    # Active batches
    if not fb.empty and 'IdBatch' in fb.columns:
        unique_batches = fb[fb['IdBatch'] > 0]['IdBatch'].nunique()
        active_steps = len(fb[fb['State'] == 2]) if 'State' in fb.columns else 0
    else:
        unique_batches = 0
        active_steps = 0
    
    col1.metric("Batches Tracked", unique_batches)
    col2.metric("Active Steps", active_steps)
    
    # Alarms
    if not al.empty:
        total_alarms = len(al)
        unique_equip_alarms = al['name'].nunique() if 'name' in al.columns else 0
    else:
        total_alarms = 0
        unique_equip_alarms = 0
    
    col3.metric("Total Alarms", total_alarms)
    col4.metric("Equipment w/ Alarms", unique_equip_alarms)
    
    # Intake events
    intake_count = len(intake) if not intake.empty else 0
    col5.metric("RM Intake Events", intake_count)
    
    st.markdown("---")
    
    # ---- CHARTS ROW 1 ----
    col1, col2 = st.columns(2)
    
    # Batch Flow Status
    with col1:
        st.subheader("Batch Flow — Equipment Status")
        if not fb.empty and 'Equipment' in fb.columns:
            status_df = fb[fb['IdBatch'] > 0].groupby(['Equipment', 'StateDesc']).size().reset_index(name='Count')
            if not status_df.empty:
                fig = px.bar(status_df, x='Equipment', y='Count', color='StateDesc',
                             color_discrete_sequence=['#1B4332', '#40916C', '#95D5B2', '#F77F00', '#D62828'],
                             barmode='stack')
                fig.update_layout(
                    margin=dict(t=10, b=10, l=10, r=10),
                    legend=dict(orientation='h', y=-0.2),
                    xaxis_tickangle=-45,
                    height=350
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No active batch data")
        else:
            st.info("No FlowBatch data loaded")
    
    # Alarm Distribution
    with col2:
        st.subheader("Alarm Distribution by Equipment")
        if not al.empty and 'name' in al.columns:
            alarm_counts = al['name'].value_counts().head(10).reset_index()
            alarm_counts.columns = ['Equipment', 'Count']
            fig = px.bar(alarm_counts, x='Count', y='Equipment', orientation='h',
                         color_discrete_sequence=['#D62828'])
            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                yaxis={'categoryorder': 'total ascending'},
                height=350
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No AlarmHistory data loaded")
    
    st.markdown("---")
    
    # ---- CHARTS ROW 2 ----
    col1, col2 = st.columns(2)
    
    # Equipment Step Duration
    with col1:
        st.subheader("Avg Processing Time per Equipment (min)")
        if not fb.empty and 'Duration_min' in fb.columns:
            dur_df = fb[fb['Duration_min'] > 0].groupby('Equipment')['Duration_min'].mean().sort_values(ascending=True).reset_index()
            if not dur_df.empty:
                fig = px.bar(dur_df, x='Duration_min', y='Equipment', orientation='h',
                             color_discrete_sequence=['#2D6A4F'])
                fig.update_layout(
                    margin=dict(t=10, b=10, l=10, r=10),
                    xaxis_title='Minutes',
                    height=350
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No duration data available")
    
    # Alarm Timeline
    with col2:
        st.subheader("Alarm Timeline")
        if not al.empty and 'dateApp' in al.columns:
            al_timeline = al.copy()
            al_timeline['Hour'] = al_timeline['dateApp'].dt.floor('h')
            hourly = al_timeline.groupby('Hour').size().reset_index(name='Alarms')
            if not hourly.empty:
                fig = px.line(hourly, x='Hour', y='Alarms', markers=True,
                              color_discrete_sequence=['#D62828'])
                fig.update_layout(
                    margin=dict(t=10, b=10, l=10, r=10),
                    height=350
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No alarm timeline data")
    
    st.markdown("---")
    
    # ---- RM INTAKE ACTIVITY ----
    st.subheader("RM Intake Activity")
    if not intake.empty and 'DateOperate' in intake.columns:
        col1, col2 = st.columns(2)
        
        with col1:
            intake_by_state = intake['StateDesc'].value_counts().reset_index()
            intake_by_state.columns = ['Status', 'Count']
            fig = px.pie(intake_by_state, values='Count', names='Status',
                         color_discrete_sequence=['#1B4332', '#40916C', '#95D5B2'])
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            intake_timeline = intake.copy()
            intake_timeline['Hour'] = intake_timeline['DateOperate'].dt.floor('h')
            hourly_intake = intake_timeline.groupby('Hour').size().reset_index(name='Events')
            if not hourly_intake.empty:
                fig = px.bar(hourly_intake, x='Hour', y='Events',
                             color_discrete_sequence=['#40916C'])
                fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300)
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No RM Intake data loaded")


# ============================================================================
# BATCH TRACKING
# ============================================================================

elif page == "Batch Tracking":
    st.title("Batch Production Tracking")
    
    if st.session_state.flowbatch_df.empty:
        st.info("No FlowBatch data loaded. Go to **Upload New Data** to load CSV files.")
        st.stop()
    
    fb = st.session_state.flowbatch_df
    
    st.markdown("---")
    
    # Batch selector
    if 'IdBatch' in fb.columns:
        batch_ids = sorted(fb[fb['IdBatch'] > 0]['IdBatch'].unique(), reverse=True)
        
        if batch_ids:
            selected_batch = st.selectbox("Select Batch ID", batch_ids,
                                          format_func=lambda x: f"Batch {x}")
            
            batch_data = fb[
                (fb['IdBatch'] == selected_batch) | 
                (fb.get('IdBatchPre', pd.Series()) == selected_batch)
            ].sort_values('FlowOrder')
            
            if not batch_data.empty:
                st.markdown("---")
                
                # Batch summary
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Batch ID", selected_batch)
                col2.metric("Equipment Steps", len(batch_data))
                
                if 'DateStart' in batch_data.columns:
                    start = batch_data['DateStart'].min()
                    end = batch_data['DateFinish'].max()
                    if pd.notna(start):
                        col3.metric("Started", start.strftime('%H:%M'))
                    if pd.notna(end):
                        col4.metric("Latest Activity", end.strftime('%H:%M'))
                
                st.markdown("---")
                
                # Flow visualization
                st.subheader("Production Flow")
                
                for _, row in batch_data.iterrows():
                    col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                    
                    with col1:
                        equip_name = row.get('Equipment', row.get('FBName', 'Unknown'))
                        st.markdown(f"**{equip_name}**")
                        st.caption(f"Step: {row.get('FBName', '')}")
                    
                    with col2:
                        if pd.notna(row.get('DateStart')):
                            st.caption(f"Start: {row['DateStart'].strftime('%m/%d %I:%M %p')}")
                        if pd.notna(row.get('DateFinish')):
                            st.caption(f"End: {row['DateFinish'].strftime('%m/%d %I:%M %p')}")
                    
                    with col3:
                        if 'Duration_min' in row and row['Duration_min'] > 0:
                            st.metric("Duration", f"{row['Duration_min']} min")
                    
                    with col4:
                        state = row.get('StateDesc', 'Unknown')
                        if state == 'Transferring':
                            st.success(state)
                        elif state in ['Filling', 'Mixing']:
                            st.warning(state)
                        elif state == 'Circuit Error':
                            st.error(state)
                        else:
                            st.info(state)
                    
                    st.markdown("---")
                
                # Raw data table
                st.subheader("Raw Batch Data")
                display_cols = ['FBName', 'Equipment', 'DateStart', 'DateFinish', 'Duration_min', 'StateDesc', 'StepFB', 'OrderFB']
                available_cols = [c for c in display_cols if c in batch_data.columns]
                st.dataframe(batch_data[available_cols], use_container_width=True, hide_index=True)
            else:
                st.info("No flow data found for this batch")
        else:
            st.info("No batch IDs found in data")
    
    st.markdown("---")
    
    # Export
    st.subheader("Export")
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        fb.to_excel(writer, sheet_name='FlowBatch', index=False)
    output.seek(0)
    st.download_button("Download FlowBatch Excel", data=output,
                       file_name=f"AC_FlowBatch_{datetime.now().strftime('%Y%m%d')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ============================================================================
# ALARM ANALYSIS
# ============================================================================

elif page == "Alarm Analysis":
    st.title("Equipment Alarm Analysis")
    
    if st.session_state.alarm_df.empty:
        st.info("No AlarmHistory data loaded. Go to **Upload New Data** to load CSV files.")
        st.stop()
    
    al = st.session_state.alarm_df
    
    st.markdown("---")
    
    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Alarms", len(al))
    col2.metric("Unique Equipment", al['name'].nunique() if 'name' in al.columns else 0)
    
    if 'AlarmDuration_min' in al.columns:
        avg_dur = al['AlarmDuration_min'].mean()
        max_dur = al['AlarmDuration_min'].max()
        col3.metric("Avg Duration", f"{avg_dur:.1f} min")
        col4.metric("Max Duration", f"{max_dur:.1f} min")
    
    st.markdown("---")
    
    # Alarm by Equipment
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Alarms by Equipment")
        if 'name' in al.columns:
            equip_alarms = al['name'].value_counts().reset_index()
            equip_alarms.columns = ['Equipment', 'Count']
            fig = px.bar(equip_alarms, x='Count', y='Equipment', orientation='h',
                         color='Count', color_continuous_scale=['#95D5B2', '#D62828'])
            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                yaxis={'categoryorder': 'total ascending'},
                showlegend=False, height=400
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("Alarms by Equipment Type")
        if 'EquipTypeDesc' in al.columns:
            type_alarms = al['EquipTypeDesc'].value_counts().reset_index()
            type_alarms.columns = ['Type', 'Count']
            fig = px.pie(type_alarms, values='Count', names='Type',
                         color_discrete_sequence=['#1B4332', '#2D6A4F', '#40916C', '#95D5B2', '#D62828'])
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=400)
            st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Alarm Timeline
    st.subheader("Alarm Timeline (Hourly)")
    if 'dateApp' in al.columns:
        al_copy = al.copy()
        al_copy['Hour'] = al_copy['dateApp'].dt.floor('h')
        hourly = al_copy.groupby('Hour').size().reset_index(name='Count')
        fig = px.area(hourly, x='Hour', y='Count',
                      color_discrete_sequence=['#D62828'])
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300)
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Top repeat offenders
    st.subheader("Top Repeat Alarm Equipment")
    if 'name' in al.columns:
        repeats = al.groupby('name').agg(
            AlarmCount=('IdRow', 'count'),
            FirstAlarm=('dateApp', 'min'),
            LastAlarm=('dateApp', 'max'),
        ).sort_values('AlarmCount', ascending=False).reset_index()
        st.dataframe(repeats, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Full alarm log
    st.subheader("Full Alarm Log")
    display_cols = ['name', 'dateApp', 'DateDis', 'AlarmDuration_min', 'EquipTypeDesc']
    available_cols = [c for c in display_cols if c in al.columns]
    st.dataframe(al[available_cols], use_container_width=True, hide_index=True)
    
    # Export
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        al.to_excel(writer, sheet_name='AlarmHistory', index=False)
    output.seek(0)
    st.download_button("Download Alarm Report Excel", data=output,
                       file_name=f"AC_AlarmReport_{datetime.now().strftime('%Y%m%d')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ============================================================================
# RM INTAKE
# ============================================================================

elif page == "RM Intake":
    st.title("Raw Material Intake Events")
    
    if st.session_state.intake_df.empty:
        st.info("No RPIntakeEvents data loaded. Go to **Upload New Data** to load CSV files.")
        st.stop()
    
    intake = st.session_state.intake_df
    
    st.markdown("---")
    
    # KPIs
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Events", len(intake))
    
    if 'StateDesc' in intake.columns:
        completed = len(intake[intake['StateDesc'] == 'Completed'])
        in_progress = len(intake[intake['StateDesc'] == 'In Progress'])
        col2.metric("Completed", completed)
        col3.metric("In Progress", in_progress)
    
    st.markdown("---")
    
    # Intake by Status
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Events by Status")
        if 'StateDesc' in intake.columns:
            status_counts = intake['StateDesc'].value_counts().reset_index()
            status_counts.columns = ['Status', 'Count']
            fig = px.pie(status_counts, values='Count', names='Status',
                         color_discrete_sequence=['#1B4332', '#40916C', '#95D5B2'])
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=350)
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("Intake Activity Over Time")
        if 'DateOperate' in intake.columns:
            intake_copy = intake.copy()
            intake_copy['Hour'] = intake_copy['DateOperate'].dt.floor('h')
            hourly = intake_copy.groupby('Hour').size().reset_index(name='Events')
            fig = px.bar(hourly, x='Hour', y='Events',
                         color_discrete_sequence=['#2D6A4F'])
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=350)
            st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Intake by ID
    st.subheader("Events by Intake ID")
    if 'IdIntake' in intake.columns:
        intake_summary = intake.groupby('IdIntake').agg(
            Events=('IdRow', 'count'),
            FirstEvent=('DateOperate', 'min'),
            LastEvent=('DateOperate', 'max'),
        ).sort_values('LastEvent', ascending=False).reset_index()
        st.dataframe(intake_summary, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Full log
    st.subheader("Full Intake Log")
    st.dataframe(intake, use_container_width=True, hide_index=True)
    
    # Export
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        intake.to_excel(writer, sheet_name='RMIntake', index=False)
    output.seek(0)
    st.download_button("Download RM Intake Excel", data=output,
                       file_name=f"AC_RMIntake_{datetime.now().strftime('%Y%m%d')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ============================================================================
# DATA EXPLORER
# ============================================================================

elif page == "Data Explorer":
    st.title("Data Explorer")
    st.caption("Explore raw SCADA data from uploaded CSV files")
    
    st.markdown("---")
    
    dataset = st.selectbox("Select Dataset", ["FlowBatch", "AlarmHistory", "RPIntakeEvents"])
    
    if dataset == "FlowBatch" and not st.session_state.flowbatch_df.empty:
        df = st.session_state.flowbatch_df
    elif dataset == "AlarmHistory" and not st.session_state.alarm_df.empty:
        df = st.session_state.alarm_df
    elif dataset == "RPIntakeEvents" and not st.session_state.intake_df.empty:
        df = st.session_state.intake_df
    else:
        st.info(f"No {dataset} data loaded. Upload CSV files first.")
        st.stop()
    
    st.markdown("---")
    
    # Stats
    col1, col2, col3 = st.columns(3)
    col1.metric("Rows", len(df))
    col2.metric("Columns", len(df.columns))
    col3.metric("Dataset", dataset)
    
    st.markdown("---")
    
    # Column info
    st.subheader("Columns")
    col_info = pd.DataFrame({
        'Column': df.columns,
        'Type': df.dtypes.astype(str),
        'Non-Null': df.notnull().sum(),
        'Sample': [str(df[c].iloc[0])[:50] if len(df) > 0 else '' for c in df.columns]
    })
    st.dataframe(col_info, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Full data
    st.subheader("Data")
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Export
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=dataset, index=False)
    output.seek(0)
    st.download_button(f"Download {dataset} Excel", data=output,
                       file_name=f"AC_{dataset}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
