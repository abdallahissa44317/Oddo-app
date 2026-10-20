from datetime import datetime
import io
import json
import xmlrpc.client
import pandas as pd
import streamlit as st

# 1. إعدادات الصفحة
st.set_page_config(
    page_title='Web app',
    page_icon='📱',
    layout='wide',
    initial_sidebar_state='expanded',
)

# 2. إعدادات الاتصال المدمجة
CONFIG = {
    'url': 'https://navybits-al-amin.odoo.com/',  # ضع هنا رابط سيرفر Odoo
    'db': '16937617',  # ضع هنا اسم قاعدة البيانات
    'accounts': [
        {
            'label': 'abu samraa',
            'username': 'أبو سمرا',
            'password': '1234',
        },
        {
            'label': 'dewar',
            'username': 'الدوار',
            'password': '1234',
        },
    ],
}


# دالة قراءة التكوين (تأخذ من Streamlit Secrets عند الرفع إن وجدت أو من CONFIG)
def get_config():
  if hasattr(st, 'secrets') and 'url' in st.secrets:
    return {
        'url': st.secrets['url'],
        'db': st.secrets['db'],
        'accounts': json.loads(st.secrets['accounts_json']),
    }
  return CONFIG


cfg = get_config()


# 3. دالة جلب الجلسات المفتوحة
def fetch_open_sessions(account):
  try:
    common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
    uid = common.authenticate(
        cfg['db'], account['username'], account['password'], {}
    )
    if not uid:
      return None, f"فشل الاتصال بالحساب: {account['label']}"

    models = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")
    domain = [('state', '=', 'opened')]

    sessions = models.execute_kw(
        cfg['db'],
        uid,
        account['password'],
        'pos.session',
        'search_read',
        [domain],
        {
            'fields': [
                'id',
                'name',
                'config_id',
                'user_id',
                'start_at',
                'cash_register_balance_start',
                'total_payments_amount',
            ]
        },
    )
    if not sessions:
      return [], None

    session_ids = [s['id'] for s in sessions]
    orders = models.execute_kw(
        cfg['db'],
        uid,
        account['password'],
        'pos.order',
        'search_read',
        [[('session_id', 'in', session_ids)]],
        {'fields': ['id', 'session_id', 'payment_ids']},
    )

    order_to_session = {}
    all_p_ids = []
    for o in orders:
      s_id = o['session_id'][0] if o.get('session_id') else None
      p_ids = o.get('payment_ids', [])
      all_p_ids.extend(p_ids)
      for pid in p_ids:
        order_to_session[pid] = s_id

    session_totals = {s_id: {'USD': 0.0, 'LBP': 0.0} for s_id in session_ids}
    if all_p_ids:
      payments = models.execute_kw(
          cfg['db'],
          uid,
          account['password'],
          'pos.payment',
          'search_read',
          [[['id', 'in', all_p_ids]]],
          {'fields': ['id', 'payment_method_id', 'currency_id', 'amount']},
      )
      for p in payments:
        amt = p.get('amount', 0.0)
        s_id = order_to_session.get(p['id'])
        if not s_id:
          continue
        m_name = (
            p['payment_method_id'][1] if p.get('payment_method_id') else ''
        )
        c_name = p['currency_id'][1] if p.get('currency_id') else ''
        comb = f'{m_name} {c_name}'.upper()
        if 'USD' in comb or '$' in comb:
          session_totals[s_id]['USD'] += amt
        elif (
            'LBP' in comb
            or 'LL' in comb
            or 'ل.ل' in comb
            or 'لبناني' in comb
        ):
          session_totals[s_id]['LBP'] += amt
        else:
          if amt < 1000:
            session_totals[s_id]['USD'] += amt
          else:
            session_totals[s_id]['LBP'] += amt

    data = []
    for s in sessions:
      s_id = s['id']
      data.append({
          'رمز الجلسة': s.get('name'),
          'الفرع': s['config_id'][1] if s.get('config_id') else 'غير محدد',
          'الكاشير': s['user_id'][1] if s.get('user_id') else 'غير محدد',
          'تاريخ الفتح': s.get('start_at'),
          'الافتتاحي كاش': s.get('cash_register_balance_start', 0.0),
          'تحصيلات دولار ($)': session_totals[s_id]['USD'],
          'تحصيلات لبناني (LBP)': session_totals[s_id]['LBP'],
          'إجمالي المدفوعات': s.get('total_payments_amount', 0.0),
      })
    return data, None
  except Exception as e:
    return None, str(e)


# 4. واجهة المستخدم Web UI
st.title('📱 تطبيق Odoo POS للمتابعة المالية')

# القائمة الجانبية
st.sidebar.header('⚙️ الخيارات')
report_type = st.sidebar.radio(
    'اختر التقرير المطلوب:', ['الجلسات المفتوحة حالياً', 'طلبات مبيعات اليوم']
)

accounts = cfg.get('accounts', [])
acc_labels = ['جميع الفروع'] + [a['label'] for a in accounts]
selected_branch = st.sidebar.selectbox('اختر الفرع:', acc_labels)

if st.sidebar.button('🔄 تحديث البيانات'):
  st.rerun()

target_accounts = (
    accounts
    if selected_branch == 'جميع الفروع'
    else [a for a in accounts if a['label'] == selected_branch]
)

all_data = []
errors = []

with st.spinner('جاري جلب البيانات من سيرفر Odoo...'):
  for acc in target_accounts:
    res, err = fetch_open_sessions(acc)
    if err:
      errors.append(err)
    elif res:
      all_data.extend(res)

if errors and not all_data:
  st.error('❌ ' + '\n'.join(errors))
elif not all_data:
  st.warning('⚠️ لا توجد بيانات متاحة حالياً لهذا الاختيار.')
else:
  df = pd.DataFrame(all_data)

  # حساب الإجماليات
  tot_usd = df['تحصيلات دولار ($)'].sum()
  tot_lbp = df['تحصيلات لبناني (LBP)'].sum()

  # عرض كروت الإحصائيات في الأعلى
  c1, c2, c3 = st.columns(3)
  c1.metric('إجمالي الدولار', f'${tot_usd:,.2f}')
  c2.metric('إجمالي اللبناني', f'{tot_lbp:,.0f} LBP')
  c3.metric('العدد الإجمالي', f'{len(df)}')

  st.divider()

  # عرض الجدول
  st.subheader(f'📌 جدول {report_type}')
  st.dataframe(df, use_container_width=True)

  # زر تحميل ملف Excel
  buffer = io.BytesIO()
  with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name='Odoo Data')

  st.download_button(
      label='📥 تنزيل ملف Excel',
      data=buffer.getvalue(),
      file_name=f"Odoo_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
      mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  )
