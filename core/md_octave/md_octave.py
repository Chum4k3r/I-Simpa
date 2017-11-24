#! /usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function  # compatibilité python 3.0

import os
import sys
# Add I-Simpa folder in lib path
from os.path import dirname
libpath = dirname(os.path.abspath(__file__ + "/../../"))
sys.path.append(libpath)
try:
    import libsimpa as ls
except ImportError:
    print("Couldn't find libsimpa in " + libpath, file=sys.stderr)
    exit(-1)

import coreConfig as cc
from subprocess import call
import shutil
import glob
import time
import kdtree
import sauve_recsurf_results


try:
    import h5py
except ImportError:
    print("h5py python module not found, cannot read hdf5 files. See www.h5py.org", file=sys.stderr)
    exit(-1)

try:
    import numpy
except ImportError:
    print("numpy python module not found", file=sys.stderr)
    exit(-1)

# Find octave program utility
def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

def process_face(tetraface, modelImport, sharedVertices, fileOut):
    if tetraface.marker >= 0:
        fileOut.write('{0:>6} {1:>6} {2:>6} {3:>6}'.format(*(
        tetraface.vertices[0] + 1, tetraface.vertices[1] + 1, tetraface.vertices[2] + 1,
        modelImport.faces[tetraface.marker].idMat)) + "\n")
        if tetraface.neighbor >= 0:
            sharedVertices.add(tetraface.vertices[0] + 1)
            sharedVertices.add(tetraface.vertices[1] + 1)
            sharedVertices.add(tetraface.vertices[2] + 1)


def write_input_files(cbinpath, cmbinpath, materials, sources_lst, outfolder):
    """
     Import 3D model
     This model contains the associated material link to the XML file
     XML volume index to octave index
    :param cbinpath:
    :param cmbinpath:
    :param materials:
    :param sources_lst:
    :param outfolder:
    :return: dictionary of loaded data or None if failed
    """
    ret = {}
    idVolumeIndex = {}
    sharedVertices = set()

    modelImport = ls.ioModel()
    if not ls.CformatBIN().ImportBIN(modelImport, cbinpath):
        print("Error can not load %s model !\n" % cbinpath)
        return None

    # Import 3D mesh file builded from tetgen output
    mesh_import = ls.CMBIN().LoadMesh(cmbinpath)
    if not mesh_import:
        print("Error can not load %s mesh model !\n" % cmbinpath)
        return None

    # Write NODES file
    with open(outfolder + "scene_nodes.txt", "w") as f:
        for node in mesh_import.nodes:
            f.write('{0:>15} {1:>15} {2:>15}'.format(*(node[0], node[1], node[2])) + "\n")

    ret["model"] = mesh_import
    ret["mesh"] = mesh_import
    # Write elements file
    with open(outfolder + "scene_elements.txt", "w") as f:
        for tetra in mesh_import.tetrahedres:
            volindex = idVolumeIndex.get(tetra.idVolume)
            if volindex is None:
                volindex = len(idVolumeIndex) + 1
                idVolumeIndex[tetra.idVolume] = len(idVolumeIndex) + 1
            f.write('{0:>6} {1:>6} {2:>6} {3:>6} {4:>6}'.format(*(
            tetra.vertices[0] + 1, tetra.vertices[1] + 1, tetra.vertices[2] + 1, tetra.vertices[3] + 1,
            volindex)) + "\n")

    # Write tetra face file
    with open(outfolder + "scene_faces.txt", "w") as f:
        for tetra in mesh_import.tetrahedres:
            process_face(tetra.getFace(0), modelImport, sharedVertices, f)
            process_face(tetra.getFace(1), modelImport, sharedVertices, f)
            process_face(tetra.getFace(2), modelImport, sharedVertices, f)
            process_face(tetra.getFace(3), modelImport, sharedVertices, f)

    # Write boundary material file
    with open(outfolder + "scene_materials_absorption.txt", "w") as f:
        for xmlid, mat in materials.iteritems():
            f.write('{0:>6} '.format(xmlid))
            # for each frequency band
            for freqAbs in mat["q"]:
                f.write(' {0:>6.2g}'.format(freqAbs))
            # end of line
            f.write("\n")

    # Write boundary material transmission file
    with open(outfolder + "scene_materials_transmission.txt", "w") as f:
        for xmlid, mat in materials.iteritems():
            f.write('{0:>6} '.format(xmlid))
            # for each frequency band
            for freqTransm in mat["g"]:
                f.write(' {0:>6.2g}'.format(freqTransm))
            # end of line
            f.write("\n")

    # Write source position and power files
    with open(outfolder + "scene_sources.txt", "w") as f:
        for src in sources_lst:
            f.write('{0:>15} {1:>15} {2:>15} '.format(src.pos[0], src.pos[1], src.pos[2]))
            # for each frequency band
            for spl in src.db:
                f.write(' {0:>6.4g}'.format(spl))
            # end of line
            f.write("\n")

    # Write shared vertices index
    with open(outfolder + "scene_shared_vertices.txt", "w") as f:
        for ptindex in sharedVertices:
            f.write(str(ptindex) + "\n")

    return ret


class ReceiverSurf:
    def __init__(self, idrs, faceid, x, y, z):
        self.coords = (x, y, z)
        self.idrs = idrs
        self.isSurfReceiver = True
        self.idrp = None
        self.faceid = faceid
        self.spl = []


    def __iter__(self):
        return self.coords.__iter__()

    def __len__(self):
        return 3

    def __getitem__(self, item):
        return self.coords[item]

    def __str__(self):
        return self.coords.__str__()


class ReceiverPunctual:
    def __init__(self, idrp, x, y, z):
        self.coords = (x, y, z)
        self.isSurfReceiver = False
        self.idrp = idrp
        self.spl = []

    def __iter__(self):
        return self.coords.__iter__()

    def __len__(self):
        return 3

    def __getitem__(self, item):
        return self.coords[item]

    def __str__(self):
        return self.coords.__str__()

def to_vec3(vec):
    return ls.vec3(vec[0], vec[1], vec[2])

def to_array(vec):
    return [vec[0], vec[1], vec[2]]

def square_dist(v1, v2):
    return sum([(v1[axis] - v2[axis])**2 for axis in range(len(v1))])

def process_output_files(outfolder, coreconf, import_data):
    data_path = os.path.join(outfolder, "scene_WStatioFields.hdf5")
    if os.path.exists(data_path):
        # Create spatial index for receivers points
        receivers_index = kdtree.create(dimensions=3)
        # For each surface receiver
        pt_count = 0
        for idrs, surface_receivers in coreconf.recsurf.iteritems():
            # For each vertex of the grid
            for faceid, receiver in enumerate(surface_receivers.GetSquaresCenter()):
                receivers_index.add(ReceiverSurf(idrs, faceid, receiver[0], receiver[1], receiver[2]))
                pt_count += 1
        # For each punctual receiver
        for idrp, rp in coreconf.recepteursponct.iteritems():
            receivers_index.add(ReceiverPunctual(idrp, rp["pos"][0], rp["pos"][1], rp["pos"][2]))
            pt_count += 1

        receivers_index.rebalance()
        # Computation done, fetch levels at tetrahedron vertices
        dataset_name = "statio_data"
        data = h5py.File(data_path, "r")
        if dataset_name in data:
            # Read power at each vertices
            sdata = data[dataset_name]
            mesh = import_data["mesh"]
            result_matrix = sdata["value"]
            num_frequencies, num_nodes = result_matrix.shape
            print("Begin export surface receiver values")
            last_perc = 0
            if num_nodes != len(mesh.nodes):
                print("Received nodes from Octave are different that provided nodes", file=sys.stderr)
                return False
            for idtetra, tetra in enumerate(mesh.tetrahedres):
                p1 = to_vec3(mesh.nodes[tetra.vertices[0]])
                p2 = to_vec3(mesh.nodes[tetra.vertices[1]])
                p3 = to_vec3(mesh.nodes[tetra.vertices[2]])
                p4 = to_vec3(mesh.nodes[tetra.vertices[3]])
                p = (p1+p2+p3+p4) / 4
                rmax = max([square_dist(p, p1), square_dist(p, p2), square_dist(p, p3), square_dist(p, p4)])
                # Fetch receivers in the tetrahedron
                # nearest_receivers = receivers_index.search_nn_dist([p[0], p[1], p[2]], rmax)
                nearest_receivers = set()
                k = 5
                while True:
                    res = receivers_index.search_knn([p[0], p[1], p[2]], k)
                    if len(res) > 0:
                        dist_arr = [square_dist(tp[0].data, p) for tp in res]
                        if len(res) < pt_count and max(dist_arr) < rmax:
                            k *= 2
                        else:
                            nearest_receivers |= set([tp[0] for tp in res])
                            break
                new_perc = int((idtetra / float(len(mesh.tetrahedres))) * 100)
                if new_perc != last_perc:
                    print("Export receivers %i %%" % new_perc)
                    last_perc = new_perc
                # Compute coefficient of the receiver point into the tetrahedron
                for nearest_receiver in nearest_receivers:
                    receiver = nearest_receiver.data
                    coefficient = get_a_coefficients(to_array(receiver), to_array(p1), to_array(p2), to_array(p3), to_array(p4))
                    if coefficient.min() > 0:
                        # Point is inside tetrahedron
                        for id_freq in range(num_frequencies):
                            # For each frequency compute the interpolated value
                            interpolated_value = coefficient[0] * result_matrix[id_freq][tetra.vertices[0]] + \
                                 coefficient[1] * result_matrix[id_freq][tetra.vertices[1]] + \
                                 coefficient[2] * result_matrix[id_freq][tetra.vertices[2]] + \
                                 coefficient[3] * result_matrix[id_freq][tetra.vertices[3]]
                            # If the receiver belongs to a surface receiver add the value into it            
                            if receiver.isSurfReceiver:
                                coreconf.recsurf[receiver.idrs].face_power[receiver.faceid].append(interpolated_value)
                            else:
                                # Into a punctual receiver
                                coreconf.recepteursponct[receiver.idrp]["power"].append(interpolated_value)

            print("End export receivers values")


def get_a_coefficients(p, p1, p2, p3, p4):
    """
        Compute the interpolation coefficient of a point into a tetrahedron
        ex: getACoefficients([2,2,0.2], [1,1,0],[3,2,0], [2,4,0], [2,2.5,3])
        source: Journal of Electronic Imaging / April 2002 / Vol. 11(2) / 161
    :param p: Any point (x,y,z)
    :param p1: p1 of tetrahedron (x,y,z)
    :param p2: p2 of tetrahedron (x,y,z)
    :param p3: p3 of tetrahedron (x,y,z)
    :param p4: p4 of tetrahedron (x,y,z)
    :return (a1,a2,a3,a4) coefficients. If point is inside of tetrahedron so all coefficient are greater than 0
    """
    left_mat = numpy.append(numpy.swapaxes(numpy.array([p1, p2, p3, p4]), 0, 1), numpy.ones((1, 4)), axis=0)
    right_mat = numpy.append(numpy.reshape(p, (3, 1)), [1])
    return numpy.dot(numpy.linalg.inv(left_mat), right_mat)


def main(call_octave=True):
    # find core folder
    scriptfolder = sys.argv[0][:sys.argv[0].rfind(os.sep)] + os.sep
    # Read I-SIMPA XML configuration file
    coreconf = cc.coreConfig(sys.argv[1])
    outputdir = coreconf.paths["workingdirectory"]
    # Translation CBIN 3D model and 3D tetrahedra mesh into Octave input files
    import_data = write_input_files(outputdir + coreconf.paths["modelName"], outputdir + coreconf.paths["tetrameshFileName"],
                      coreconf.materials, coreconf.sources_lst, outputdir)
    # Copy octave script to working dir
    matscript_folder = os.path.join(os.path.abspath(os.path.join(os.path.realpath(__file__), os.pardir)), "script")
    files = glob.iglob(os.path.join(matscript_folder, "*.m"))
    print(os.path.join(matscript_folder, "*.m"))
    for filep in files:
        if os.path.isfile(filep):
            shutil.copy2(filep, outputdir)
    if call_octave:
        # Check if octave program are accessible in path
        octave = which("octave-cli.exe")
        if octave is None:
            print("Octave program not in system path, however input files are created", file=sys.stderr)
        else:
            command = ["octave-cli", "--no-window-system", "--verbose", outputdir + "MVCEF3D.m"]
            print("Run " + " ".join(command))
            deb = time.time()
            call(command, cwd=outputdir, shell=True)
            print("Execution in %.2f seconds" % ((time.time() - deb) / 1000.))
    process_output_files(outputdir, coreconf, import_data)
    sauve_recsurf_results.SauveRecepteurSurfResults(coreconf)

if __name__ == '__main__':
    main(sys.argv[-1] != "noexec")
