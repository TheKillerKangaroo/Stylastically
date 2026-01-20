import arcpy
import json
import os

class Toolbox(object):
    def __init__(self):
        self.label = "CIM Corporate Style Tools"
        self.alias = "CIMStyles"
        self.tools = [CreateStyleFromLayer, ApplyStyleToLayer]

# ==========================================
# TOOL 1: CREATE STYLE (Unchanged)
# ==========================================
class CreateStyleFromLayer(object):
    def __init__(self):
        self.label = "1. Create Style from Layer"
        self.description = "Extracts styling into a clean .lyrx file."
        self.canRunInBackground = False

    def getParameterInfo(self):
        param0 = arcpy.Parameter(
            displayName="Source Layer Files (.lyrx)",
            name="in_layer_files",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        param0.filter.list = ["lyrx"]

        param1 = arcpy.Parameter(
            displayName="Style Library Folder",
            name="out_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )
        return [param0, param1]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        lyrx_files_string = parameters[0].valueAsText
        output_folder = parameters[1].valueAsText
        if not lyrx_files_string: return

        file_list = [f.strip("'") for f in lyrx_files_string.split(';')]
        messages.addMessage(f"Creating styles from {len(file_list)} file(s)...")

        for file_path in file_list:
            try:
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                output_filename = f"{base_name}_Style.lyrx"
                output_path = os.path.join(output_folder, output_filename)

                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if "layerDefinitions" in data:
                    for layer in data["layerDefinitions"]:
                        if "featureTable" in layer and "dataConnection" in layer["featureTable"]:
                            # We deliberately break the link here so it's a template
                            layer["featureTable"]["dataConnection"] = None
                
                with open(output_path, 'w', encoding='utf-8') as f_out:
                    json.dump(data, f_out, indent=4)
                
                messages.addMessage(f"   Saved: {output_filename}")

            except Exception as e:
                messages.addWarningMessage(f"   Failed {file_path}: {str(e)}")
        return

# ==========================================
# TOOL 2: APPLY STYLE (CIM Injection Method)
# ==========================================
class ApplyStyleToLayer(object):
    def __init__(self):
        self.label = "2. Apply Corporate Style to Layer"
        self.description = "Replaces the target layer and forces a CIM data connection transplant."
        self.canRunInBackground = False

    def getParameterInfo(self):
        param0 = arcpy.Parameter(
            displayName="Style Library Folder",
            name="style_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )

        param1 = arcpy.Parameter(
            displayName="Select Corporate Style",
            name="style_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        param1.parameterDependencies = [param0.name]

        param2 = arcpy.Parameter(
            displayName="Target Layer",
            name="target_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )
        
        return [param0, param1, param2]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        try:
            style_folder = parameters[0].valueAsText
            style_name = parameters[1].valueAsText

            if style_folder and os.path.exists(style_folder) and not parameters[1].filter.list:
                try:
                    style_files = [f for f in os.listdir(style_folder) if f.endswith('_Style.lyrx')]
                    parameters[1].filter.list = style_files
                except:
                    pass 
            
            if style_folder and style_name:
                full_style_path = os.path.join(style_folder, style_name)
                if os.path.exists(full_style_path):
                    try:
                        with open(full_style_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)  
                        geom_type = data["layerDefinitions"][0]["featureTable"]["geometryType"]
                        geo_map = {
                            "esriGeometryPolygon": "Polygon",
                            "esriGeometryPoint": "Point",
                            "esriGeometryPolyline": "Polyline",
                            "esriGeometryMultipoint": "Multipoint"
                        }
                        target_shape = geo_map.get(geom_type, None)
                        if target_shape:
                            aprx = arcpy.mp.ArcGISProject("CURRENT")
                            m = aprx.activeMap
                            if m:
                                valid_layers = [l.name for l in m.listLayers() if l.isFeatureLayer and l.shapeType == target_shape]
                                parameters[2].filter.list = valid_layers
                    except:
                        pass
        except:
            pass
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        style_folder = parameters[0].valueAsText
        style_name = parameters[1].valueAsText
        target_layer_name = parameters[2].valueAsText 
        
        style_path = os.path.join(style_folder, style_name)
        messages.addMessage(f"Loading style: {style_name}")

        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap
            
            # 1. Find the REAL Old Layer Object
            old_layer = None
            for lyr in active_map.listLayers():
                if lyr.name == target_layer_name:
                    old_layer = lyr
                    break
            
            if not old_layer:
                messages.addErrorMessage(f"Could not find layer '{target_layer_name}'")
                return

            # 2. Extract Data Connection from Old Layer (The Heart)
            try:
                old_cim = old_layer.getDefinition('V3')
                if not hasattr(old_cim, "featureTable") or not hasattr(old_cim.featureTable, "dataConnection"):
                    messages.addErrorMessage("Target layer is not a standard feature layer (no data connection found).")
                    return
                
                # Grab the connection object
                data_connection = old_cim.featureTable.dataConnection
                messages.addMessage(" - Extracted Data Connection from target.")
            except Exception as ex:
                messages.addErrorMessage(f"Failed to read target layer definition: {str(ex)}")
                return

            # 3. Insert the New Style Layer (The Body)
            messages.addMessage(" - Inserting Corporate Style Layer...")
            style_lyr_file = arcpy.mp.LayerFile(style_path)
            new_layer = active_map.insertLayer(old_layer, style_lyr_file, "AFTER")
            
            if not new_layer:
                messages.addErrorMessage("Failed to insert the style layer.")
                return

            # 4. Perform the Transplant
            # We overwrite the new layer's empty connection with the valid one
            try:
                messages.addMessage(" - Injecting Data Connection...")
                new_cim = new_layer.getDefinition('V3')
                
                # Direct Injection
                new_cim.featureTable.dataConnection = data_connection
                
                # Apply changes
                new_layer.setDefinition(new_cim)
                
            except Exception as ex:
                messages.addErrorMessage(f"Failed to inject data connection: {str(ex)}")
                # Clean up if failed
                active_map.removeLayer(new_layer)
                return

            # 5. Restore Metadata & Cleanup
            new_layer.name = old_layer.name
            if old_layer.definitionQuery:
                new_layer.definitionQuery = old_layer.definitionQuery
            
            messages.addMessage(" - Removing old layer...")
            active_map.removeLayer(old_layer)
            
            messages.addMessage("Success: Style applied via CIM Injection.")

        except Exception as e:
            messages.addErrorMessage(f"Critical Error: {str(e)}")

        return
    
