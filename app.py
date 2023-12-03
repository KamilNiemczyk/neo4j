from flask import Flask, jsonify, request
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os 

load_dotenv()

app = Flask(__name__)

uri = os.getenv('URI')
user = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "test1234"))

def get_employees(tx, sort=None, filter=None):
    query="MATCH (m:Employee)"
    if filter:
        query+=f" WHERE {filter}"
    query+=" RETURN m"
    if sort:
        query+=f" ORDER BY m.{sort}"
    results=tx.run(query).data()
    employees=[{'name': result['m']['name'], 'stanowisko' : result['m']['position']} for result in results]
    return employees

@app.route('/employees', methods=['GET'])
def get_employees_route():
    sort = request.args.get('sort')
    filter = request.args.get('filter')
    with driver.session() as session:
        pracownicy = session.execute_read(get_employees, sort, filter)
    response = {'pracownicy': pracownicy}
    return jsonify(response)

def czy_istnieje_pracownik(tx, name):
    query = "MATCH (m:Employee {name: $name}) RETURN m"
    result = tx.run(query, name=name).data()
    return bool(result)

def czy_istnieje_department(tx, name):
    query = "MATCH (d:Department {name: $name}) RETURN d"
    results = tx.run(query, name=name).data()
    return bool(results)

@app.route('/employees', methods=['POST'])
def add_employee():
    name = request.json['name']
    position = request.json['position']
    department = request.json['department']
    with driver.session() as session:
        if not session.execute_read(czy_istnieje_pracownik, name):
            if session.execute_read(czy_istnieje_department, department):
                query = "MATCH (d:Department {name: $department}) CREATE (m:Employee {name: $name, position: $position})-[:WORKS_IN]->(d)"
                session.run(query, name=name, position=position, department=department)
                response = {'message': f'Employee {name} added to {department}'}
            else:
                response = {'message': f'Department {department} does not exist'}
        else:
            response = {'message': f'Employee {name} already exists'}
    return jsonify(response)

def czy_istnieje_po_id(tx, id):
    query = f"MATCH (e:Employee) WHERE id(e)=$id RETURN e"
    result = tx.run(query, id=int(id)).data()
    return bool(result)

def edytuj_pracownika(tx, id, name, position, department):
    query = f"MATCH (e:Employee) WHERE id(e)=$id SET e.name=$name, e.position=$position"
    if department:
        query += ", (e)-[:WORKS_IN]->(:Department {name: $department})"
    tx.run(query, id=int(id), name=name, position=position, department=department)

@app.route('/employees/<id>', methods=['PUT'])
def edit_employee(id):
    name = request.json['name']
    position = request.json['position']
    department = request.json['department']
    with driver.session() as session:
        if session.execute_read(czy_istnieje_po_id, id):
            session.execute_write(edytuj_pracownika, id, name, position, department)
            response = {'message': f'Udało się edytować pracownika o id {id}'}
        else:
            response = {'message': f'Nie ma takiego pracownika'}
    return jsonify(response)

def usun_pracownika(tx, id):
    query = f"MATCH (e:Employee) WHERE id(e)=$id DETACH DELETE e"
    tx.run(query, id=int(id))
def usun_department(tx, id):
    query = (
        "MATCH (d:Department)<-[r:MANAGES]-(m:Employee) "
        "WHERE ID(m) = $id "
        "WITH d, m, r "
        "DELETE d, r "
        "WITH m "
        "SET m:EmployeeWithoutDepartment"
    )
    tx.run(query, id=id)
@app.route('/employees/<id>', methods=['DELETE'])
def delete_employee(id):
    with driver.session() as session:
        if session.execute_read(czy_istnieje_po_id, id):
            session.execute_write(usun_department, id)
            session.execute_write(usun_pracownika, id)
            response = {'message': f'Udało się usunąć pracownika o id {id}'}
        else:
            response = {'message': f'Nie ma takiego pracownika'}
    return jsonify(response)

def czy_manager(tx, id):
    query = (
        "MATCH (e:Employee)-[r]->() "
        "WHERE id(e) = $id "
        "RETURN r"
    )
    results = tx.run(query, id=int(id)).data()
    is_manager = any(result['r'][1] == 'MANAGES' for result in results)
    return is_manager

def jaki_department(tx, id):
    query = ("MATCH (e:Employee)-[:WORKS_IN]->(d:Department) "
                "WHERE id(e) = $id "
                "RETURN d")
    result = tx.run(query, id=int(id)).data()
    department = result[0]['d']['name']
    return department

def ile_pracownikow(tx, department):
    query = ("MATCH (e:Employee)-[:WORKS_IN]->(d:Department) "
                "WHERE d.name = $department "
                "RETURN count(e) as count")
    result = tx.run(query, department=department).data()
    return result
@app.route('/employees/<id>/subordinates', methods=['GET'])
def get_subordinates(id):
    with driver.session() as session:
        if session.execute_read(czy_istnieje_po_id, id):
            if session.execute_read(czy_manager, id):
                department = session.execute_read(jaki_department, id)
                result = session.execute_read(ile_pracownikow, department)
                response = {'message': f'W dziale {department} jest {result[0]["count"]} pracownikow'}
            else:
                response = {'message': f'Pracownik o id {id} nie jest managerem'}
        else:
            response = {'message': f'Nie ma takiego pracownika'}
    return jsonify(response)

def lista_departamentow(tx, order_by, desc=False):
    query = f"MATCH (d:Department) RETURN d ORDER BY d.{order_by} {'DESC' if desc else ''}"
    results = tx.run(query).data()
    return results

@app.route('/departments', methods=['GET'])
def get_departments():
    order_by = request.args.get('order_by', 'name')
    desc = request.args.get('desc', '').lower() == 'true' 
    with driver.session() as session:
        departments = session.read_transaction(lista_departamentow, order_by, desc)
    response = {'departments': departments}
    return jsonify(response)

def pracownicy_departamentu(tx, department_id):
    query = (
        "MATCH (department:Department)-[:HAS_EMPLOYEE]->(employee:Employee) "
        "WHERE ID(department) = $department_id "
        "RETURN employee"
    )
    results = tx.run(query, department_id=department_id).data()
    return results

@app.route('/departments/<int:department_id>/employees', methods=['GET'])
def get_department_employees(department_id):
    with driver.session() as session:
        if not session.execute_read(czy_istnieje_department, department_id):
            return jsonify({'message': f'Department with ID {department_id} does not exist'}), 404
        employees = session.read_transaction(pracownicy_departamentu, department_id)
    response = {'employees': employees}
    return jsonify(response)

if __name__ == '__main__':
    app.run()

