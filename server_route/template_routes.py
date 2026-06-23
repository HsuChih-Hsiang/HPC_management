from flask import Blueprint, request, jsonify
from database.extensions import db
from database.hpc_model import EmailTemplate
from sqlalchemy.exc import IntegrityError

template_bp = Blueprint('template', __name__)

# 模擬獲取當前使用者，未來可從 session 獲取
def get_current_user():
    return "admin"

@template_bp.route('/api/templates', methods=['GET', 'POST'])
def handle_templates():
    username = get_current_user()
    
    if request.method == 'GET':
        templates = EmailTemplate.query.filter_by(owner_username=username).all()
        return jsonify([t.to_dict() for t in templates])
    
    elif request.method == 'POST':
        data = request.get_json()
        name = data.get('name')
        subject = data.get('subject', '')
        html = data.get('html')
        
        if not name or not html:
            return jsonify({'success': False, 'message': '模板名稱和內容不能為空。'}), 400
        
        try:
            new_template = EmailTemplate(
                name=name,
                subject=subject,
                html=html,
                owner_username=username
            )
            db.session.add(new_template)
            db.session.commit()
            return jsonify({'success': True, 'message': '模板已成功儲存！', 'template': new_template.to_dict()})
        except IntegrityError:
            db.session.rollback()
            return jsonify({'success': False, 'message': '該模板名稱已存在。'}), 409

@template_bp.route('/api/templates/<int:template_id>', methods=['GET', 'PUT', 'DELETE'])
def manage_template(template_id):
    username = get_current_user()
    
    # 確保查詢時帶上使用者條件，防止越權操作
    template = EmailTemplate.query.filter_by(id=template_id, owner_username=username).first()
    
    if not template:
        return jsonify({'success': False, 'message': '模板未找到。'}), 404

    if request.method == 'GET':
        return jsonify(template.to_dict())

    elif request.method == 'PUT':
        data = request.get_json()
        template.name = data.get('name', template.name)
        template.subject = data.get('subject', template.subject)
        template.html = data.get('html', template.html)
        
        try:
            db.session.commit()
            return jsonify({'success': True, 'message': '模板已成功更新！'})
        except IntegrityError:
            db.session.rollback()
            return jsonify({'success': False, 'message': '更新失敗：模板名稱可能已存在。'}), 409

    elif request.method == 'DELETE':
        db.session.delete(template)
        db.session.commit()
        return jsonify({'success': True, 'message': '模板已成功刪除。'})