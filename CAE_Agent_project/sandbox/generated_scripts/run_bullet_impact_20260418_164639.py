from abaqus import *
from abaqusConstants import *
from caeModules import *
from driverUtils import executeOnCaeStartup
import os
os.chdir(r"G:\Abaqus\agent_project")
mdb.saveAs(pathName='G:/Abaqus/agent_project/bullet')
executeOnCaeStartup()
s = mdb.models['Model-1'].ConstrainedSketch(name='__profile__', 
    sheetSize=500.0)
g, v, d, c = s.geometry, s.vertices, s.dimensions, s.constraints
s.setPrimaryObject(option=STANDALONE)
s.rectangle(point1=(0.0, 0.0), point2=(200.0, 200.0))
p = mdb.models['Model-1'].Part(name='Part-1', dimensionality=THREE_D, 
    type=DEFORMABLE_BODY)
p = mdb.models['Model-1'].parts['Part-1']
p.BaseSolidExtrude(sketch=s, depth=20.0)
s.unsetPrimaryObject()
p = mdb.models['Model-1'].parts['Part-1']
del mdb.models['Model-1'].sketches['__profile__']
s1 = mdb.models['Model-1'].ConstrainedSketch(name='__profile__', 
    sheetSize=500.0)
g, v, d, c = s1.geometry, s1.vertices, s1.dimensions, s1.constraints
s1.setPrimaryObject(option=STANDALONE)
s1.ConstructionLine(point1=(0.0, -250.0), point2=(0.0, 250.0))
s1.FixedConstraint(entity=g[2])
s1.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(20.0, 0.0))
s1.Line(point1=(0.0, 20.0), point2=(0.0, -20.0))
s1.VerticalConstraint(entity=g[4], addUndoState=False)
s1.ParallelConstraint(entity1=g[2], entity2=g[4], addUndoState=False)
s1.CoincidentConstraint(entity1=v[2], entity2=g[2], addUndoState=False)
s1.CoincidentConstraint(entity1=v[3], entity2=g[2], addUndoState=False)
s1.autoTrimCurve(curve1=g[3], point1=(-20.0 * 0.5, 20.0 * 0.5))
p = mdb.models['Model-1'].Part(name='bullet', dimensionality=THREE_D, 
    type=DISCRETE_RIGID_SURFACE)
p = mdb.models['Model-1'].parts['bullet']
p.BaseShellRevolve(sketch=s1, angle=360.0, flipRevolveDirection=OFF)
s1.unsetPrimaryObject()
p = mdb.models['Model-1'].parts['bullet']
del mdb.models['Model-1'].sketches['__profile__']
p = mdb.models['Model-1'].parts['bullet']
v1, e, d1, n = p.vertices, p.edges, p.datums, p.nodes
p.ReferencePoint(point=p.InterestingPoint(edge=e[0], rule=CENTER))
p = mdb.models['Model-1'].parts['Part-1']
mdb.models['Model-1'].parts.changeKey(fromName='Part-1', toName='plate')
mdb.models['Model-1'].Material(name='HPB 300 snap')
mdb.models['Model-1'].materials['HPB 300 snap'].DuctileDamageInitiation(table=(
    (1.0, 0.0, 30.0), (0.5, 0.4, 30.0)))
mdb.models['Model-1'].materials['HPB 300 snap'].ductileDamageInitiation.DamageEvolution(
    type=DISPLACEMENT, table=((0.02, ), ))
mdb.models['Model-1'].materials['HPB 300 snap'].Density(table=((7.85e-09, ), ))
mdb.models['Model-1'].materials['HPB 300 snap'].Elastic(table=((210000.0, 0.3), ))
mdb.models['Model-1'].materials['HPB 300 snap'].Plastic(scaleStress=None, 
    table=((300.0, 0.0), (321.46, 0.01), (329.41, 0.02), (334.58, 0.1), (
    355.64, 0.15), (366.37, 0.4), (378.69, 1.0), (437.1, 4.0)))
mdb.models['Model-1'].HomogeneousSolidSection(name='Section-1', 
    material='HPB 300 snap', thickness=None)
p = mdb.models['Model-1'].parts['plate']
c = p.cells
cells = c.getSequenceFromMask(mask=('[#1 ]', ), )
region = regionToolset.Region(cells=cells)
p = mdb.models['Model-1'].parts['plate']
p.SectionAssignment(region=region, sectionName='Section-1', offset=0.0, 
    offsetType=MIDDLE_SURFACE, offsetField='', 
    thicknessAssignment=FROM_SECTION)
p = mdb.models['Model-1'].parts['bullet']
p = mdb.models['Model-1'].parts['bullet']
r = p.referencePoints
refPoints=(r[2], )
p.Set(referencePoints=refPoints, name='Set-p')
a = mdb.models['Model-1'].rootAssembly
a = mdb.models['Model-1'].rootAssembly
a.DatumCsysByDefault(CARTESIAN)
p = mdb.models['Model-1'].parts['bullet']
a.Instance(name='bullet-1', part=p, dependent=ON)
p = mdb.models['Model-1'].parts['plate']
a.Instance(name='plate-1', part=p, dependent=ON)
p1 = a.instances['plate-1']
p1.translate(vector=(40.0, 0.0, 0.0))
a = mdb.models['Model-1'].rootAssembly
a.rotate(instanceList=('plate-1', ), axisPoint=(40.0, 0.0, 0.0), 
    axisDirection=(10.0, 0.0, 0.0), angle=90.0)
a1 = mdb.models['Model-1'].rootAssembly
e11 = a1.instances['plate-1'].edges
a1.DatumPointByMidPoint(point1=a1.instances['plate-1'].InterestingPoint(
    edge=e11[2], rule=MIDDLE), point2=a1.instances['plate-1'].InterestingPoint(
    edge=e11[9], rule=MIDDLE))
a = mdb.models['Model-1'].rootAssembly
a.translate(instanceList=('bullet-1', ), vector=(0.0, 100.0, 0.0))
a = mdb.models['Model-1'].rootAssembly
a.translate(instanceList=('plate-1', ), vector=(-140.0, 0.0, -100.0))
mdb.models['Model-1'].ExplicitDynamicsStep(name='Step-1', previous='Initial', timePeriod=0.01, improvedDtMethod=ON)
mdb.models['Model-1'].fieldOutputRequests['F-Output-1'].setValues(variables=(
    'S', 'SVAVG', 'PE', 'PEVAVG', 'PEEQ', 'PEEQVAVG', 'LE', 'U', 'V', 'A', 
    'RF', 'CSTRESS', 'EVF', 'STATUS'))
p = mdb.models['Model-1'].parts['bullet']
p = mdb.models['Model-1'].parts['bullet']
p.seedPart(size=4.5, deviationFactor=0.1, minSizeFactor=0.1)
p = mdb.models['Model-1'].parts['bullet']
p.generateMesh()
p = mdb.models['Model-1'].parts['plate']
p = mdb.models['Model-1'].parts['plate']
p.seedPart(size=6.0, deviationFactor=0.1, minSizeFactor=0.1)
p = mdb.models['Model-1'].parts['plate']
p.generateMesh()
a = mdb.models['Model-1'].rootAssembly
a = mdb.models['Model-1'].rootAssembly
a.regenerate()
a1 = mdb.models['Model-1'].rootAssembly
n1 = a1.instances['plate-1'].nodes
nodes1 = n1.getSequenceFromMask(mask=('[#ffffffff:144 #ffff ]', ), )
a1.Set(nodes=nodes1, name='Set-node')
mdb.models['Model-1'].ContactProperty('IntProp-1')
mdb.models['Model-1'].interactionProperties['IntProp-1'].TangentialBehavior(
    formulation=PENALTY, directionality=ISOTROPIC, slipRateDependency=OFF, 
    pressureDependency=OFF, temperatureDependency=OFF, dependencies=0, table=((
    0.1, ), ), shearStressLimit=None, maximumElasticSlip=FRACTION, 
    fraction=0.005, elasticSlipStiffness=None)
mdb.models['Model-1'].interactionProperties['IntProp-1'].NormalBehavior(
    pressureOverclosure=HARD, allowSeparation=ON, 
    constraintEnforcementMethod=DEFAULT)
a1 = mdb.models['Model-1'].rootAssembly
s1 = a1.instances['bullet-1'].faces
side1Faces1 = s1.getSequenceFromMask(mask=('[#1 ]', ), )
region1=regionToolset.Region(side1Faces=side1Faces1)
a1 = mdb.models['Model-1'].rootAssembly
region2=a1.sets['Set-node']
mdb.models['Model-1'].SurfaceToSurfaceContactExp(name ='Int-1', 
    createStepName='Step-1', main = region1, secondary = region2, 
    mechanicalConstraint=KINEMATIC, sliding=FINITE, 
    interactionProperty='IntProp-1', initialClearance=OMIT, datumAxis=None, 
    clearanceRegion=None)
a1 = mdb.models['Model-1'].rootAssembly
v1 = a1.instances['bullet-1'].vertices
verts1 = v1.getSequenceFromMask(mask=('[#3 ]', ), )
r1 = a1.instances['bullet-1'].referencePoints
refPoints1=(r1[2], )
region=regionToolset.Region(vertices=verts1, referencePoints=refPoints1)
mdb.models['Model-1'].rootAssembly.engineeringFeatures.PointMassInertia(
    name='Inertia-1', region=region, mass=0.1, i22=0.1, alpha=0.0, 
    composite=0.0)
a1 = mdb.models['Model-1'].rootAssembly
f1 = a1.instances['plate-1'].faces
faces1 = f1.getSequenceFromMask(mask=('[#5 ]', ), )
region = regionToolset.Region(faces=faces1)
mdb.models['Model-1'].EncastreBC(name='BC-1', createStepName='Initial', 
    region=region, localCsys=None)
a1 = mdb.models['Model-1'].rootAssembly
r1 = a1.instances['bullet-1'].referencePoints
refPoints1=(r1[2], )
region = regionToolset.Region(referencePoints=refPoints1)
mdb.models['Model-1'].Velocity(name='Predefined Field-1', region=region, 
    field='', distributionType=MAGNITUDE, velocity1=0.0, velocity2=-100000.0, 
    velocity3=0.0, omega=0.0)
p = mdb.models['Model-1'].parts['plate']
elemType1 = mesh.ElemType(elemCode=C3D8R, elemLibrary=EXPLICIT, 
    kinematicSplit=AVERAGE_STRAIN, secondOrderAccuracy=OFF, 
    hourglassControl=DEFAULT, distortionControl=DEFAULT)
elemType2 = mesh.ElemType(elemCode=C3D6, elemLibrary=EXPLICIT)
elemType3 = mesh.ElemType(elemCode=C3D4, elemLibrary=EXPLICIT)
p = mdb.models['Model-1'].parts['plate']
c = p.cells
cells = c.getSequenceFromMask(mask=('[#1 ]', ), )
pickedRegions =(cells, )
p.setElementType(regions=pickedRegions, elemTypes=(elemType1, elemType2, 
    elemType3))
p = mdb.models['Model-1'].parts['bullet']
a = mdb.models['Model-1'].rootAssembly
a.regenerate()
a = mdb.models['Model-1'].rootAssembly
mdb.Job(name='Job-1', model='Model-1', description='', type=ANALYSIS, 
    atTime=None, waitMinutes=0, waitHours=0, queue=None, memory=90, 
    memoryUnits=PERCENTAGE, explicitPrecision=SINGLE, 
    nodalOutputPrecision=SINGLE, echoPrint=OFF, modelPrint=OFF, 
    contactPrint=OFF, historyPrint=OFF, userSubroutine='', scratch='', 
    resultsFormat=ODB, numDomains=1, activateLoadBalancing=False, 
    numThreadsPerMpiProcess=1, multiprocessingMode=DEFAULT, numCpus=1)
mdb.jobs['Job-1'].submit(consistencyChecking=OFF)
o3 = session.openOdb(name='G:/Abaqus/agent_project/Job-1.odb')
session.animationOptions.setValues(frameRate=4)
mdb.save()